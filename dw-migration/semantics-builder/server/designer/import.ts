import type { SemanticBrief } from '../../shared/brief';
import type { TestCase } from '../../shared/designer';
import { validateMetricView } from '../../shared/metricView';
import type { Join } from '../../shared/metricView';

const TABLE = /^[^\s().]+\.[^\s().]+\.[^\s().]+$/;
const sourcesOf = (joins: Join[] | undefined): string[] =>
  (joins ?? []).flatMap((j) => [j.source, ...sourcesOf(j.joins)]);

function aggregationOf(expr: string): SemanticBrief['measures'][number]['aggregation'] {
  const e = expr.trim().toUpperCase();
  if (/^COUNT\s*\(\s*DISTINCT\b/.test(e)) return 'count_distinct';
  for (const [re, agg] of [
    [/^SUM\s*\(/, 'sum'],
    [/^COUNT\s*\(/, 'count'],
    [/^AVG\s*\(/, 'avg'],
    [/^MIN\s*\(/, 'min'],
    [/^MAX\s*\(/, 'max'],
  ] as const)
    if (re.test(e) && !/\)\s*\//.test(e)) return agg;
  return /\//.test(e) ? 'ratio' : 'other';
}

/** A metric view from Unity Catalog as app objects: its source tables, a brief draft, the design and tests. */
export function importDesign(fullName: string, yaml: string) {
  const { view, issues } = validateMetricView(yaml);
  if (!view) throw new Error(`${fullName} is not a valid metric view: ${issues[0]?.message ?? 'no YAML'}`);
  const short = fullName.split('.').pop() ?? fullName;
  const name =
    short
      .toLowerCase()
      .replace(/[^a-z0-9_]/g, '_')
      .replace(/^[^a-z]+/, '')
      .slice(0, 100) || 'imported_metrics';
  const sources = [...new Set([view.source, ...sourcesOf(view.joins)].filter((s) => TABLE.test(s.trim())))].slice(
    0,
    30
  );
  const first = view.measures[0].name;
  const tests: TestCase[] = [
    { name: `${first} in total`, dimensions: [], measures: [first] },
    ...view.dimensions
      .slice(0, 2)
      .map((d) => ({ name: `${first} by ${d.name}`, dimensions: [d.name], measures: [first] })),
  ];
  const brief: SemanticBrief = {
    title: short.replace(/_/g, ' ').slice(0, 200),
    businessGoal: (view.comment ?? `Metrics of ${fullName}.`).slice(0, 2000),
    audience: [],
    keyQuestions: [view.dimensions[0] ? `What is ${first} by ${view.dimensions[0].name}?` : `What is ${first}?`],
    measures: view.measures.slice(0, 50).map((m) => ({
      name: m.name.slice(0, 100),
      aggregation: aggregationOf(m.expr),
      description: (m.comment ?? '').slice(0, 1000),
    })),
    dimensions: view.dimensions
      .slice(0, 50)
      .map((d) => ({ name: d.name.slice(0, 100), description: (d.comment ?? '').slice(0, 1000) })),
    timeGrains: [],
    candidateSources: sources,
    glossary: [],
    assumptions: [`Imported from ${fullName}.`],
    openQuestions: [],
  };
  return { view, issues, name, sources, brief, tests, yaml };
}
