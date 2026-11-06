import { describe, expect, it } from 'vitest';
import { consolidate, kpisOfMetricView, kpisOfSqlView, normalizeExpr, normalizeName } from './consolidate';

const yaml = (measures: string) => `version: 1.1
source: main.sales.orders
dimensions:
  - name: Region
    expr: region
measures:
${measures}`;

describe('normalize', () => {
  it('ignores case, quotes, qualifiers and spaces', () => {
    expect(normalizeExpr('SUM( o.`Amount` )')).toBe(normalizeExpr('sum(amount)'));
    expect(normalizeExpr('SUM(price * 1.5)')).toBe('sum(price*1.5)');
  });
  it('ignores filler words and case styles', () => {
    expect(normalizeName('Total Revenue')).toBe('revenue');
    expect(normalizeName('total_revenue')).toBe('revenue');
    expect(normalizeName('TotalRevenue')).toBe('revenue');
    expect(normalizeName('Total')).toBe('total');
  });
});

describe('kpisOfSqlView', () => {
  it('finds named aggregations in select lists, with or without AS', () => {
    const sql = `SELECT region, SUM(o.amount) AS revenue, count(DISTINCT customer_id) customers,
      ROUND(AVG(price), 2) AS avg_price, MAX(x)
      FROM main.sales.orders o GROUP BY region`;
    expect(kpisOfSqlView('v', sql).map((k) => [k.name, k.expr])).toEqual([
      ['revenue', 'SUM(o.amount)'],
      ['customers', 'count(DISTINCT customer_id)'],
      ['avg_price', 'ROUND(AVG(price), 2)'],
      ['MAX(x)', 'MAX(x)'],
    ]);
  });
  it('reads subqueries and skips plain columns', () => {
    const sql = 'SELECT a FROM (SELECT a, sum(b) AS b_total FROM t GROUP BY a) s';
    expect(kpisOfSqlView('v', sql).map((k) => k.name)).toEqual(['b_total']);
  });
});

describe('consolidate', () => {
  it('groups the same KPI across views and flags a formula conflict', () => {
    const kpis = [
      ...kpisOfMetricView('m.s.mv', yaml('  - name: Total Revenue\n    expr: SUM(amount)')),
      ...kpisOfSqlView('m.s.v1', 'SELECT SUM(o.amount) AS revenue FROM t o'),
      ...kpisOfSqlView('m.s.v2', 'SELECT SUM(amount - discount) AS revenue FROM t'),
      ...kpisOfSqlView('m.s.v3', 'SELECT COUNT(*) AS rows FROM t'),
    ];
    const groups = consolidate(kpis);
    expect(groups).toHaveLength(1);
    expect(groups[0].conflict).toBe(true);
    expect(groups[0].canonical).toMatchObject({ view: 'm.s.mv', name: 'Total Revenue' });
    expect(groups[0].replaces).toEqual(['m.s.v1', 'm.s.v2']);
  });
  it('groups the same formula under different names without a conflict', () => {
    const groups = consolidate([
      ...kpisOfSqlView('a', 'SELECT COUNT(DISTINCT order_id) AS order_count FROM t'),
      ...kpisOfSqlView('b', 'SELECT count(distinct o.order_id) AS orders FROM t o'),
    ]);
    expect(groups).toHaveLength(1);
    expect(groups[0].conflict).toBe(false);
  });
  it('tells a formula conflict on one table from the same name on other tables', () => {
    const [g] = consolidate([
      ...kpisOfSqlView('a', 'SELECT COUNT(DISTINCT customer_id) AS customers FROM main.shop.orders'),
      ...kpisOfSqlView('b', 'SELECT COUNT(DISTINCT `cust`) AS customers FROM `main`.`crm`.`accounts`'),
    ]);
    expect(g.kpis.map((k) => k.source)).toEqual(['main.shop.orders', 'main.crm.accounts']);
    expect(g).toMatchObject({ conflict: false, differentTables: true });
  });
  it('ignores a KPI that only one view has', () => {
    expect(consolidate(kpisOfSqlView('a', 'SELECT SUM(x) AS x1, SUM(x) AS x2 FROM t'))).toEqual([]);
  });
});
