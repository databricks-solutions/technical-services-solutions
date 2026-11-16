import type { Explanations, TestCase } from '../../shared/designer';
import type { Join, MetricView, SourceProfiles } from '../../shared/metricView';
import type { DesignOutput } from '../llm/prompts/designer';
import { quoteId } from '../readiness/profile';
import type { TableProfile } from '../readiness/profile';

export const toSourceProfiles = (profiles: TableProfile[]): SourceProfiles =>
  Object.fromEntries(profiles.map((p) => [p.fullName.toLowerCase(), p]));

const column = (c: string) => (/^[A-Za-z_]\w*$/.test(c) ? c : quoteId(c));

class InvalidDesign extends Error {
  constructor(reason: string) {
    super(`The model did not return valid output: ${reason}`);
  }
}

type Field = DesignOutput['dimensions'][number];
const toField = (f: Field) => ({
  name: f.name,
  expr: f.expr,
  ...(f.comment ? { comment: f.comment } : {}),
  ...(f.displayName ? { display_name: f.displayName } : {}),
  ...(f.synonyms.length ? { synonyms: f.synonyms } : {}),
  ...(f.format ? { format: f.format } : {}),
});

/** Turns the model's structured design into a metric view. The server, not the model, writes join conditions. */
export function buildDesign(out: DesignOutput, sourceNames: string[]) {
  const known = new Map(sourceNames.map((s) => [s.toLowerCase(), s]));
  const table = (name: string) => {
    const match = known.get(name.toLowerCase());
    if (!match) throw new InvalidDesign(`${name} is not a project table`);
    return match;
  };

  const nodes = new Map<string, Join>();
  const roots: Join[] = [];
  for (const j of out.joins) {
    if (nodes.has(j.name) || j.name === 'source') throw new InvalidDesign(`join name ${j.name} is not unique`);
    const parent = j.parent === null ? undefined : nodes.get(j.parent);
    if (j.parent !== null && !parent) throw new InvalidDesign(`join ${j.name} comes before its parent ${j.parent}`);
    const from = j.parent ?? 'source';
    const node: Join = {
      name: j.name,
      source: table(j.source),
      on: j.keys.map((k) => `${from}.${column(k.parentColumn)} = ${j.name}.${column(k.column)}`).join(' AND '),
    };
    nodes.set(j.name, node);
    if (parent) (parent.joins ??= []).push(node);
    else roots.push(node);
  }

  const view: MetricView = {
    version: '1.1',
    source: table(out.source),
    ...(out.comment ? { comment: out.comment } : {}),
    ...(out.filter ? { filter: out.filter } : {}),
    ...(roots.length ? { joins: roots } : {}),
    dimensions: out.dimensions.map(toField),
    measures: out.measures.map((m) => ({
      ...toField(m),
      ...(m.window?.length
        ? {
            window: m.window.map((w) => ({
              order: w.order,
              range: w.range,
              ...(w.semiadditive ? { semiadditive: w.semiadditive } : {}),
              ...(w.offset ? { offset: w.offset } : {}),
            })),
          }
        : {}),
    })),
  };

  const explanations: Explanations = {
    summary: out.summary,
    dimensions: Object.fromEntries(out.dimensions.map((d) => [d.name, { explanation: d.explanation }])),
    measures: Object.fromEntries(
      out.measures.map((m) => [m.name, { additivity: m.additivity, explanation: m.explanation }])
    ),
  };
  return { name: out.name, view, explanations, tests: keepValidTests(out.tests, view) };
}

/** Drops test cases that name fields the view does not have. */
export function keepValidTests(tests: TestCase[], view: MetricView): TestCase[] {
  const dims = new Set(view.dimensions.map((d) => d.name));
  const measures = new Set(view.measures.map((m) => m.name));
  return tests.filter(
    (t) =>
      t.measures.length > 0 &&
      t.measures.every((m) => measures.has(m)) &&
      t.dimensions.every((d) => dims.has(d)) &&
      (t.expect?.filters ?? []).every((f) => dims.has(f.dimension))
  );
}
