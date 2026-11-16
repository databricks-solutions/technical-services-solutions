import { describe, expect, it } from 'vitest';
import type { TestCase } from '../../shared/designer';
import { runAccessCheck } from './access';

const tests: TestCase[] = [
  { name: 'By region', dimensions: ['Region'], measures: ['Revenue'] },
  { name: 'Total', dimensions: [], measures: ['Revenue'], expect: { value: 100, tolerancePct: 1, filters: [] } },
  { name: 'Masked', dimensions: ['Customer'], measures: ['Revenue'] },
];

describe('runAccessCheck', () => {
  it('keeps the status, the row count and the difference, and reports an error per test', async () => {
    const seen: string[] = [];
    const results = await runAccessCheck(
      'main.gold.sales',
      tests,
      { actor: 'a@b.com', projectId: 'p' },
      {
        execute: (sql) => {
          seen.push(sql);
          if (sql.includes('`Customer`')) return Promise.reject(new Error('PERMISSION_DENIED'));
          return Promise.resolve(
            sql.includes('GROUP BY')
              ? { columns: ['Region', 'Revenue'], rows: [['EU', '1'], ['US', '2']] }
              : { columns: ['Revenue'], rows: [['90']] }
          );
        },
        audit: () => Promise.resolve(),
      }
    );
    expect(results.map((r) => [r.name, r.status, r.rows])).toEqual([
      ['By region', 'passed', 2],
      ['Total', 'failed', 1],
      ['Masked', 'error', 0],
    ]);
    expect(results[1].detail).toContain('10%');
    expect(results[1].detail).not.toContain('90');
    expect(seen).toHaveLength(3);
  });
});
