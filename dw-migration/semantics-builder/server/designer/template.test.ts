import { describe, expect, it } from 'vitest';
import { validateMetricView, renderMetricView } from '../../shared/metricView';
import type { TableProfile } from '../readiness/profile';
import { buildDesign } from './build';
import { templateDesign } from './template';

const t = (fullName: string, cols: [string, string][], fks: TableProfile['foreignKeys'] = []): TableProfile => ({
  fullName,
  comment: '',
  columns: cols.map(([name, type]) => ({ name, type, comment: '' })),
  primaryKey: [],
  foreignKeys: fks,
});

const orders = t('c.tpch.orders', [
  ['o_orderkey', 'bigint'],
  ['o_custkey', 'bigint'],
  ['o_totalprice', 'decimal(18,2)'],
  ['o_orderdate', 'date'],
  ['o_comment', 'string'],
]);
const customer = t('c.tpch.customer', [
  ['c_custkey', 'bigint'],
  ['c_name', 'string'],
  ['c_nationkey', 'bigint'],
]);
const nation = t('c.tpch.nation', [
  ['n_nationkey', 'bigint'],
  ['n_name', 'string'],
]);

describe('templateDesign', () => {
  it('builds a valid view from the fact table, its joins, amounts and dates, with no model', () => {
    const out = templateDesign([orders, customer, nation], 'c.tpch.orders');
    expect(out.source).toBe('c.tpch.orders');
    expect(out.joins.map((j) => [j.name, j.parent])).toEqual([
      ['dim_customer', null],
      ['dim_nation', 'dim_customer'],
    ]);
    expect(out.measures.map((m) => [m.name, m.expr])).toEqual([
      ['Row Count', 'COUNT(1)'],
      ['Total Totalprice', 'SUM(source.o_totalprice)'],
    ]);
    expect(out.dimensions.map((d) => d.name)).toEqual(['Orderdate', 'Orderdate Month', 'Customer Name', 'Nation Name']);
    expect(out.dimensions.find((d) => d.name === 'Nation Name')?.expr).toBe('dim_customer.dim_nation.n_name');
    expect(out.tests.length).toBeGreaterThan(0);

    const design = buildDesign(
      out,
      [orders, customer, nation].map((p) => p.fullName)
    );
    const { issues } = validateMetricView(renderMetricView(design.view));
    expect(issues.filter((i) => i.severity === 'error')).toEqual([]);
  });

  it('picks the table with the most outgoing keys as the fact table when no role is known', () => {
    const tx = t('c.bake.sales_transactions', [
      ['transactionID', 'bigint'],
      ['customerID', 'bigint'],
      ['totalPrice', 'bigint'],
      ['unitPrice', 'bigint'],
      ['dateTime', 'timestamp'],
    ]);
    const cust = t('c.bake.sales_customers', [
      ['customerID', 'bigint'],
      ['city', 'string'],
    ]);
    const out = templateDesign([cust, tx]);
    expect(out.source).toBe('c.bake.sales_transactions');
    expect(out.joins.map((j) => j.keys)).toEqual([[{ parentColumn: 'customerID', column: 'customerID' }]]);
    expect(out.measures.map((m) => m.name)).toEqual(['Row Count', 'Total Price', 'Average Unit Price']);
  });
});
