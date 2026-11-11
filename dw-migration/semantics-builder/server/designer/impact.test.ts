import { describe, expect, it } from 'vitest';
import { validateMetricView } from '../../shared/metricView';
import { checkStatement } from '../sql/allowlist';
import { fieldChanges, impactQuery, toConsumers, watched } from './impact';

const view = (fields: string, filter = '') =>
  validateMetricView(`version: 1.1
source: c.s.orders
${filter ? `filter: ${filter}\n` : ''}dimensions:
  - name: Region
    expr: region
${fields}`).view!;

describe('impact analysis', () => {
  it('finds removed, renamed, changed and added fields, and a new filter', () => {
    const before = view(`  - name: Segment
    expr: segment
measures:
  - name: Revenue
    expr: SUM(amount)
  - name: Orders
    expr: COUNT(1)`);
    const after = view(
      `  - name: Market segment
    expr: segment
measures:
  - name: revenue
    expr: SUM(net_amount)
  - name: Margin
    expr: SUM(margin)`,
      "status = 'done'"
    );
    const c = fieldChanges(before, after);
    expect(c).toEqual({
      removed: ['Orders'],
      renamed: [{ from: 'Segment', to: 'Market segment' }],
      changed: ['Revenue'],
      added: ['Margin'],
      filterChanged: true,
    });
    expect(watched(c)).toEqual(['Orders', 'Segment', 'Revenue']);
    expect(fieldChanges(before, before).filterChanged).toBe(false);
  });

  it('reads table and column lineage for the watched fields with escaped literals, as a read', () => {
    const sql = impactQuery('Main.Sales.Orders', ["Rev'enue"]);
    expect(sql).toContain("WHERE l.source_table_full_name = 'main.sales.orders'");
    expect(sql).toContain("lower(l.source_column_name) IN ('rev\\'enue')");
    expect(sql).not.toContain('query.history');
    expect(checkStatement(impactQuery('a.b.c', [])).kind).toBe('read');
    expect(checkStatement(sql).kind).toBe('read');
  });

  it('maps rows to consumers with the fields they use', () => {
    expect(
      toConsumers(
        [
          ['genie_space', 'abc', '3', '12', '2026-11-01T00:00:00Z', '["orders"]'],
          ['adhoc', null, '5', '40', '2026-11-02T00:00:00Z', null],
        ],
        ['Orders', 'Revenue']
      )
    ).toEqual([
      { kind: 'genie_space', id: 'abc', users: 3, queries: 12, lastUsed: '2026-11-01T00:00:00Z', uses: ['Orders'] },
      { kind: 'adhoc', id: null, users: 5, queries: 40, lastUsed: '2026-11-02T00:00:00Z', uses: [] },
    ]);
  });
});
