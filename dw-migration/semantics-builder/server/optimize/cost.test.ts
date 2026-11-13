import { describe, expect, it } from 'vitest';
import type { StressQueryResult, StressRun } from '../../shared/optimize';
import { budgetCheck, costOf, usedThisMonth } from './cost';

const query = (label: string, warmMs: number, attempts: StressQueryResult['attempts'], matched?: string | null) => ({
  label,
  dimensions: [],
  measures: ['M'],
  origin: 'generated' as const,
  sql: '',
  attempts,
  coldMs: warmMs,
  warmMs,
  maxMs: warmMs,
  readBytes: null,
  rowsRead: null,
  flags: [],
  ...(matched === undefined ? {} : { matched }),
});

const run = (over: Partial<StressRun>): StressRun => ({
  id: 'r1',
  version: 1,
  sandboxView: 'c.s.v',
  settings: { repeats: 2, targetMs: 5000 },
  status: 'finished',
  error: null,
  createdBy: 'a@x.com',
  createdAt: '2026-11-05T10:00:00.000Z',
  finishedAt: null,
  queries: [],
  materialization: null,
  ...over,
});

const base = run({
  queries: [
    query('A', 3000, [
      { wallMs: 3500, execMs: 3000, taskMs: 9000, readBytes: 100 },
      { wallMs: 40, execMs: 40, fromCache: true },
    ]),
    query('B', 1000, [{ wallMs: 1200 }]),
  ],
});

describe('costOf', () => {
  it('adds execution time, task time and bytes, and counts cached runs', () => {
    expect(costOf(base)).toMatchObject({
      kind: 'stress',
      statements: 3,
      execMs: 3000 + 40 + 1200,
      taskMs: 9000,
      readBytes: 100,
      cachedRuns: 1,
    });
  });

  it('reports the time a try saves on matched queries', () => {
    const t = run({
      id: 'r2',
      queries: [query('A', 200, [{ wallMs: 250, execMs: 200 }], 'mv_a'), query('B', 1100, [{ wallMs: 1100 }], null)],
      materialization: {
        schedule: 'every 24 hours',
        views: [{ name: 'mv_a', type: 'aggregated', dimensions: [], measures: [], queries: [], reason: '' }],
        yaml: '',
        baseRun: 'r1',
        refreshMs: 90_000,
        pipelineUrl: 'https://h/#joblist/pipelines/6d145ece-880f-4518-8a48-1bb75ecf201a/updates/x',
      },
    });
    expect(costOf(t, base)).toMatchObject({
      kind: 'try',
      matched: 1,
      savedMsPerRun: 2800,
      refreshMs: 90_000,
      pipelineId: '6d145ece-880f-4518-8a48-1bb75ecf201a',
      views: ['mv_a'],
    });
  });
});

describe('budget', () => {
  it('sums this month only', () => {
    const old = run({ id: 'old', createdAt: '2026-10-31T23:00:00.000Z', queries: base.queries });
    expect(usedThisMonth([costOf(base), costOf(old)], new Date('2026-11-20T00:00:00Z'))).toBe(4240);
  });

  it('refuses a run that would pass the budget, with the estimate', () => {
    expect(budgetCheck(null, 10_000, 5, 1000)).toBeNull();
    expect(budgetCheck(20_000, 10_000, 5, 1000)).toBeNull();
    expect(budgetCheck(12_000, 10_000, 5, 1000)).toMatch(/about 5\.0 s/);
    expect(budgetCheck(10_000, 10_000, 1, 0)).toMatch(/used/);
  });
});
