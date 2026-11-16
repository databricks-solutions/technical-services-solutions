import { createHash } from 'node:crypto';
import type { SemanticBrief } from '../../shared/brief';
import type { TestCase } from '../../shared/designer';
import type { TuningChange } from '../../shared/genie';
import { quoteId, quoteName } from '../readiness/profile';
import { expectQuery } from '../designer/validate';

const MAX_SAMPLES = 10;
export const MAX_MATCHED = 50;
const MAX_TEXT = 25_000;

/** Stable ids: the same design gives the same JSON, so the reviewed JSON can be compared before it runs. */
const idOf = (kind: string, text: string) => createHash('sha256').update(`${kind}\n${text}`).digest('hex').slice(0, 32);
const byId = <T extends { id: string }>(items: T[]) => items.sort((a, b) => a.id.localeCompare(b.id));
const unique = (items: string[]) => [...new Set(items.map((s) => s.trim()).filter(Boolean))];

/** A plain test as the SQL a user would write: the dimensions and the measures, grouped. */
const exampleQuery = (view: string, t: Pick<TestCase, 'measures' | 'dimensions'>) =>
  `SELECT ${[...t.dimensions.map(quoteId), ...t.measures.map((m) => `MEASURE(${quoteId(m)}) AS ${quoteId(m)}`)].join(', ')} FROM ${quoteName(view)}${t.dimensions.length ? ' GROUP BY ALL' : ''}`;

/**
 * The Genie space settings (serialized_space version 2) from the design: the view, text instructions from the
 * brief, sample questions from the key questions, example SQL from the plain tests, and benchmarks from the
 * tests with an expected value. Field synonyms and descriptions come from the view itself. Text dimensions get
 * entity matching and format assistance, so Genie maps the values that users type to the stored values.
 */
export function spaceConfig(
  view: string,
  brief: SemanticBrief | null,
  tests: TestCase[],
  textDimensions: string[] = [],
  /** Changes a person approved and the benchmarks kept (i3). */
  kept: TuningChange[] = []
) {
  const lines = [
    `Answer with the metric view ${view}. Use MEASURE() for each measure and GROUP BY ALL.`,
    ...(brief
      ? [
          `Goal: ${brief.businessGoal}`,
          ...(brief.audience.length ? [`Audience: ${brief.audience.join(', ')}.`] : []),
          ...brief.glossary.map((g) => `${g.term}: ${g.definition}`),
          ...brief.assumptions.map((a) => `Rule: ${a}`),
        ]
      : []),
    ...kept.flatMap((k) => (k.kind === 'instruction' ? [k.text] : [])),
  ];
  const samples = unique(brief?.keyQuestions ?? []).slice(0, MAX_SAMPLES);
  // A benchmark is not also an example, so Genie cannot copy its answer.
  const benchmarks = tests.filter((t) => t.expect);
  const examples = [
    ...tests.filter((t) => !t.expect),
    ...kept.flatMap((k) =>
      k.kind === 'example' ? [{ name: k.question, measures: k.measures, dimensions: k.dimensions }] : []
    ),
  ];
  // Text dimensions get entity matching. Kept synonyms and descriptions go on the same column entry.
  const columns = new Map<string, Record<string, unknown>>();
  const column = (name: string) => columns.get(name) ?? columns.set(name, { column_name: name }).get(name)!;
  for (const name of unique(textDimensions).slice(0, MAX_MATCHED))
    Object.assign(column(name), { enable_entity_matching: true, enable_format_assistance: true });
  for (const k of kept) {
    if (k.kind === 'synonym') {
      const c = column(k.field);
      c.synonyms = unique([...((c.synonyms as string[]) ?? []), ...k.synonyms]);
    }
    if (k.kind === 'description') column(k.field).description = [k.text];
  }
  const columnConfigs = [...columns.values()].sort((a, b) =>
    (a.column_name as string) < (b.column_name as string) ? -1 : 1
  );
  return {
    version: 2,
    ...(samples.length
      ? { config: { sample_questions: byId(samples.map((q) => ({ id: idOf('sample', q), question: [q] }))) } }
      : {}),
    data_sources: {
      tables: [
        {
          identifier: view,
          ...(columnConfigs.length ? { column_configs: columnConfigs } : {}),
        },
      ],
    },
    instructions: {
      // Genie joins the content items with no separator, so the lines go in one item.
      text_instructions: [{ id: idOf('text', view), content: [lines.join('\n').slice(0, MAX_TEXT)] }],
      ...(examples.length
        ? {
            example_question_sqls: byId(
              examples.map((t) => ({
                id: idOf('example', t.name),
                question: [t.name],
                sql: [exampleQuery(view, t)],
              }))
            ),
          }
        : {}),
    },
    ...(benchmarks.length
      ? {
          benchmarks: {
            questions: byId(
              benchmarks.map((t) => ({
                id: idOf('benchmark', t.name),
                question: [t.name],
                answer: [{ format: 'SQL', content: [expectQuery(view, t)] }],
              }))
            ),
          },
        }
      : {}),
  };
}

export interface AgentPart {
  /** The sub-project name, shown to Genie with its instructions. */
  name: string;
  view: string;
  brief: SemanticBrief | null;
  tests: TestCase[];
  textDimensions: string[];
  kept: TuningChange[];
}

/**
 * The settings of the production Genie agent of a project: the promoted views of the chosen sub-projects in one
 * space. Each part is built like a sandbox space, then joined. Ids get the view, so the same test name in two
 * sub-projects stays two items. Genie takes one text instruction, so each sub-project gets a section in it.
 */
export function agentConfig(parts: AgentPart[]) {
  const built = [...parts]
    .sort((a, b) => a.view.localeCompare(b.view))
    .map((p) => ({ p, c: spaceConfig(p.view, p.brief, p.tests, p.textDimensions, p.kept) }));
  const scoped = <T extends { id: string }>(view: string, items: T[] = []) =>
    items.map((i) => ({ ...i, id: idOf('agent', `${view}\n${i.id}`) }));
  const samples = unique(built.flatMap(({ c }) => c.config?.sample_questions.map((q) => q.question[0]) ?? [])).slice(
    0,
    MAX_SAMPLES
  );
  const text = built
    .map(({ p, c }) => [`About ${p.name} (${p.view}):`, c.instructions.text_instructions[0].content[0]].join('\n'))
    .join('\n\n')
    .slice(0, MAX_TEXT);
  const examples = built.flatMap(({ p, c }) => scoped(p.view, c.instructions.example_question_sqls));
  const benchmarks = built.flatMap(({ p, c }) => scoped(p.view, c.benchmarks?.questions));
  return {
    version: 2,
    ...(samples.length
      ? { config: { sample_questions: byId(samples.map((q) => ({ id: idOf('sample', q), question: [q] }))) } }
      : {}),
    data_sources: { tables: built.flatMap(({ c }) => c.data_sources.tables) },
    instructions: {
      text_instructions: [{ id: idOf('text', built.map(({ p }) => p.view).join('\n')), content: [text] }],
      ...(examples.length ? { example_question_sqls: byId(examples) } : {}),
    },
    ...(benchmarks.length ? { benchmarks: { questions: byId(benchmarks) } } : {}),
  };
}
