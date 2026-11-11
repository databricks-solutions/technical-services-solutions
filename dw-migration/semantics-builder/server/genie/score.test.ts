import { describe, expect, it } from 'vitest';
import type { SemanticBrief } from '../../shared/brief';
import type { MetricView } from '../../shared/metricView';
import { scoreAgent } from './score';

const view = {
  version: '1.1',
  source: 'c.s.orders',
  comment: 'Orders.',
  dimensions: [
    { name: 'Region', expr: 'region', comment: 'Sales region.', synonyms: ['area'] },
    { name: 'Order Date', expr: 'order_date' },
  ],
  measures: [{ name: 'Revenue', expr: 'SUM(price)', comment: 'Total price.' }],
} as MetricView;
const brief = {
  title: 'Revenue',
  businessGoal: 'Track revenue.',
  audience: ['Finance'],
  keyQuestions: ['Revenue by region?', 'Revenue by month?', 'Top region?'],
  glossary: [] as SemanticBrief['glossary'],
  assumptions: ['Exclude returns.'],
} as SemanticBrief;
const statusOf = (s: ReturnType<typeof scoreAgent>) => Object.fromEntries(s.checks.map((c) => [c.id, c.status]));

describe('scoreAgent', () => {
  it('scores the design and names a fix for each gap', () => {
    const s = scoreAgent({
      view,
      brief,
      tests: [{ name: 'By region', measures: ['Revenue'], dimensions: ['Region'] }],
      matched: ['Region'],
      space: { current: false },
    });
    expect(statusOf(s)).toEqual({
      view_comment: 'pass',
      field_comments: 'warn',
      synonyms: 'warn',
      instructions: 'pass',
      samples: 'pass',
      examples: 'warn',
      benchmarks: 'fail',
      entity_matching: 'pass',
      space_current: 'fail',
    });
    expect(s.score).toBe(61);
    expect(s.checks.find((c) => c.id === 'benchmarks')?.fix?.path).toBe('designer?tab=tests');
    expect(s.checks.find((c) => c.id === 'space_current')?.detail).toMatch(/Update the view and the space/);
  });

  it('fails a design with no brief and no space', () => {
    const s = scoreAgent({ view: null, brief: null, tests: [], matched: null, space: null });
    expect(statusOf(s).instructions).toBe('fail');
    expect(statusOf(s).entity_matching).toBe('warn');
    expect(s.score).toBeLessThan(10);
  });
});
