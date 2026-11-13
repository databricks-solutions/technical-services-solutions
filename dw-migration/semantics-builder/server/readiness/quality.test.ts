import { describe, expect, it } from 'vitest';
import { checkStatement } from '../sql/allowlist';
import type { TableProfile } from './profile';
import { dataChecks, historyQuery, lastWrite, qualityQuery } from './quality';

const profile: TableProfile = {
  fullName: 'main.sales.orders',
  comment: '',
  columns: [
    { name: 'order_id', type: 'bigint', comment: '' },
    { name: 'status', type: 'string', comment: '' },
    { name: 'tags', type: 'map<string,string>', comment: '' },
    { name: 'region', type: 'string', comment: '' },
  ],
  primaryKey: ['order_id'],
  foreignKeys: [],
};
const status = (checks: ReturnType<typeof dataChecks>) => Object.fromEntries(checks.map((c) => [c.id, c.status]));

describe('data checks', () => {
  it('builds one read query, with no distinct count on a map and empty strings on text only', () => {
    const sql = qualityQuery(profile);
    expect(checkStatement(sql).kind).toBe('read');
    expect(sql).toContain("count_if(trim(`status`) = '') AS e1");
    expect(sql).not.toContain('approx_count_distinct(`tags`)');
    expect(sql).not.toContain('e0');
    expect(checkStatement(historyQuery(profile)).kind).toBe('read');
  });

  it('finds null keys, null and constant columns, empty strings and old data', () => {
    const counts = {
      columns: ['n', 'n0', 'd0', 'n1', 'e1', 'd1', 'n2', 'n3', 'e3', 'd3'],
      rows: [['10', '1', '9', '0', '2', '3', '10', '0', '0', '1']],
    };
    const checks = dataChecks(profile, counts, new Date('2026-01-01'), new Date('2026-11-11'));
    expect(status(checks)).toEqual({
      rows: 'pass',
      freshness: 'warn',
      key_nulls: 'fail',
      nulls: 'fail',
      empty_strings: 'warn',
      constant: 'warn',
    });
    const detail = Object.fromEntries(checks.map((c) => [c.id, c.detail]));
    expect(detail.key_nulls).toBe('Nulls in order_id (10%).');
    expect(detail.nulls).toBe('Always null: tags.');
    expect(detail.empty_strings).toContain('status (20%)');
    expect(detail.constant).toContain('region');
  });

  it('fails an empty table and reports a view with no history', () => {
    const checks = dataChecks(profile, { columns: ['n'], rows: [['0']] }, undefined);
    expect(status(checks).rows).toBe('fail');
    expect(checks.find((c) => c.id === 'freshness')?.detail).toMatch(/No table history/);
  });

  it('takes the last data write from the history, not maintenance', () => {
    const history = {
      columns: ['version', 'timestamp', 'operation'],
      rows: [
        ['3', '2026-11-10T00:00:00Z', 'VACUUM END'],
        ['2', '2026-11-09T00:00:00Z', 'OPTIMIZE'],
        ['1', '2026-11-01T00:00:00Z', 'MERGE'],
      ],
    };
    expect(lastWrite(history)?.toISOString()).toBe('2026-11-01T00:00:00.000Z');
    expect(lastWrite({ columns: history.columns, rows: history.rows.slice(0, 2) })).toBeNull();
    // A clone copies the data, so it counts.
    expect(lastWrite({ columns: history.columns, rows: [['1', '2026-11-03T00:00:00Z', 'CLONE']] })).not.toBeNull();
  });
});
