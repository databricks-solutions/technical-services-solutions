import { describe, expect, it } from 'vitest';
import type { SemanticBrief } from '../../shared/brief';
import { spaceConfig } from './space';

const brief = {
  title: 'Revenue',
  businessGoal: 'Track net revenue.',
  audience: ['Finance'],
  keyQuestions: ['Net revenue by region?', 'Net revenue by region?', 'Top customers?'],
  glossary: [{ term: 'Net revenue', definition: 'After discounts.' }],
  assumptions: ['Exclude returns.'],
} as SemanticBrief;
const tests = [
  { name: 'Revenue by region', measures: ['Net Revenue'], dimensions: ['Region'] },
  {
    name: 'Asia total',
    measures: ['Net Revenue'],
    dimensions: [],
    expect: { value: 12.5, tolerancePct: 1, filters: [{ dimension: 'Region', value: 'ASIA' }] },
  },
];

describe('spaceConfig', () => {
  const c = spaceConfig('c.s.v', brief, tests);

  it('builds the space from the brief and the tests, with ids sorted and unique', () => {
    expect(c.data_sources).toEqual({ tables: [{ identifier: 'c.s.v' }] });
    expect(c.config?.sample_questions.map((q) => q.question[0]).sort()).toEqual([
      'Net revenue by region?',
      'Top customers?',
    ]);
    expect(c.instructions.text_instructions[0]?.content[0]?.split('\n')).toEqual([
      'Answer with the metric view c.s.v. Use MEASURE() for each measure and GROUP BY ALL.',
      'Goal: Track net revenue.',
      'Audience: Finance.',
      'Net revenue: After discounts.',
      'Rule: Exclude returns.',
    ]);
    const ids = [
      ...(c.config?.sample_questions ?? []),
      ...(c.instructions.example_question_sqls ?? []),
      ...(c.benchmarks?.questions ?? []),
      ...c.instructions.text_instructions,
    ].map((x) => x.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) expect(id).toMatch(/^[0-9a-f]{32}$/);
    const samples = c.config?.sample_questions.map((q) => q.id) ?? [];
    expect(samples).toEqual([...samples].sort());
  });

  it('puts a test with an expected value in benchmarks only, and never the value', () => {
    expect(c.instructions.example_question_sqls).toEqual([
      expect.objectContaining({
        question: ['Revenue by region'],
        sql: ['SELECT `Region`, MEASURE(`Net Revenue`) AS `Net Revenue` FROM `c`.`s`.`v` GROUP BY ALL'],
      }),
    ]);
    expect(c.benchmarks?.questions).toEqual([
      expect.objectContaining({
        question: ['Asia total'],
        answer: [
          {
            format: 'SQL',
            content: ["SELECT MEASURE(`Net Revenue`) AS `Net Revenue` FROM `c`.`s`.`v` WHERE `Region` = 'ASIA'"],
          },
        ],
      }),
    ]);
    expect(JSON.stringify(c)).not.toContain('12.5');
  });

  it('gives the same JSON for the same design', () => {
    expect(JSON.stringify(spaceConfig('c.s.v', brief, tests))).toBe(JSON.stringify(c));
  });
});
