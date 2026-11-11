import { createHash } from 'node:crypto';
import type { SemanticBrief } from '../../shared/brief';
import type { TestCase } from '../../shared/designer';
import { quoteId, quoteName } from '../readiness/profile';
import { expectQuery } from '../designer/validate';

const MAX_SAMPLES = 10;
const MAX_TEXT = 25_000;

/** Stable ids: the same design gives the same JSON, so the reviewed JSON can be compared before it runs. */
const idOf = (kind: string, text: string) => createHash('sha256').update(`${kind}\n${text}`).digest('hex').slice(0, 32);
const byId = <T extends { id: string }>(items: T[]) => items.sort((a, b) => a.id.localeCompare(b.id));
const unique = (items: string[]) => [...new Set(items.map((s) => s.trim()).filter(Boolean))];

/** A plain test as the SQL a user would write: the dimensions and the measures, grouped. */
const exampleQuery = (view: string, t: TestCase) =>
  `SELECT ${[...t.dimensions.map(quoteId), ...t.measures.map((m) => `MEASURE(${quoteId(m)}) AS ${quoteId(m)}`)].join(', ')} FROM ${quoteName(view)}${t.dimensions.length ? ' GROUP BY ALL' : ''}`;

/**
 * The Genie space settings (serialized_space version 2) from the design: the view, text instructions from the
 * brief, sample questions from the key questions, example SQL from the plain tests, and benchmarks from the
 * tests with an expected value. Field synonyms and descriptions come from the view itself.
 */
export function spaceConfig(view: string, brief: SemanticBrief | null, tests: TestCase[]) {
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
  ];
  const samples = unique(brief?.keyQuestions ?? []).slice(0, MAX_SAMPLES);
  // A benchmark is not also an example, so Genie cannot copy its answer.
  const benchmarks = tests.filter((t) => t.expect);
  const examples = tests.filter((t) => !t.expect);
  return {
    version: 2,
    ...(samples.length
      ? { config: { sample_questions: byId(samples.map((q) => ({ id: idOf('sample', q), question: [q] }))) } }
      : {}),
    data_sources: { tables: [{ identifier: view }] },
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
