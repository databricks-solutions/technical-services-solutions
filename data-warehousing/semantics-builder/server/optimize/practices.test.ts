import { describe, expect, it } from 'vitest';
import { validateMetricView } from '../../shared/metricView';
import { bestPractices } from './practices';

const view = validateMetricView(`version: 1.1
source: c.s.orders
fields:
  - name: Order Month
    expr: DATE_TRUNC('MONTH', o_orderdate)
    comment: Month of the order.
  - name: Customer Key
    expr: o_custkey
measures:
  - name: Revenue
    expr: SUM(o_totalprice)
    comment: Total order value.
    synonyms: [sales]
    display_name: Revenue
    format:
      type: currency
      currency_code: USD
  - name: Customers
    expr: COUNT(DISTINCT o_custkey)
  - name: Revenue per Customer
    expr: MEASURE(Revenue) / MEASURE(Customers)
`).view!;

const byId = (id: string) => bestPractices(view).find((c) => c.id === id)!;

describe('bestPractices', () => {
  it('lists fields without a comment, and passes the view comment rule when there is none to check', () => {
    expect(byId('comments').fields).toEqual(['Customers', 'Revenue per Customer', 'Customer Key']);
    expect(byId('view_comment').fields).toEqual(['(view)']);
  });

  it('asks for synonyms and display names on measures only', () => {
    expect(byId('genie_names').fields).toEqual(['Customers', 'Revenue per Customer']);
  });

  it('finds ratios without NULLIF and missing formats', () => {
    expect(byId('safe_ratio').fields).toEqual(['Revenue per Customer']);
    expect(byId('formats').fields).toEqual(['Revenue per Customer', 'Order Month']);
  });

  it('flags key columns used as dimensions and notes non-additive measures', () => {
    expect(byId('high_cardinality').fields).toEqual(['Customer Key']);
    expect(byId('non_additive')).toMatchObject({ severity: 'info', fields: ['Customers'], instruction: null });
  });

  it('builds an instruction only when a fixable rule fails', () => {
    expect(byId('comments').instruction).toContain('Customer Key');
    const clean = validateMetricView(`version: 1.1
source: c.s.t
comment: A view.
measures:
  - name: Row Count
    expr: COUNT(1)
    comment: Rows.
    synonyms: [rows]
    display_name: Rows
    format:
      type: number
`).view!;
    expect(
      bestPractices(clean)
        .filter((c) => c.fields.length)
        .map((c) => c.id)
    ).toEqual([]);
  });
});
