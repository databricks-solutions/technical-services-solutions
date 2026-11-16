import { describe, expect, it } from 'vitest';
import { semanticBriefSchema } from '../../shared/brief';
import { importDesign } from './import';

const yaml = `version: 1.1
comment: Revenue of wholesale orders
source: cat.tpch.lineitem
joins:
  - name: dim_orders
    source: cat.tpch.orders
    "on": source.l_orderkey = dim_orders.o_orderkey
    joins:
      - name: dim_customer
        source: cat.tpch.customer
        "on": dim_orders.o_custkey = dim_customer.c_custkey
dimensions:
  - name: Order Month
    expr: DATE_TRUNC('MONTH', dim_orders.o_orderdate)
  - name: Customer Name
    expr: dim_orders.dim_customer.c_name
measures:
  - name: Net Revenue
    expr: SUM(source.l_extendedprice * (1 - source.l_discount))
    comment: Revenue after discounts
  - name: Customers
    expr: COUNT(DISTINCT dim_orders.o_custkey)
`;

describe('importDesign', () => {
  it('builds sources, a valid brief draft, a design and tests from a UC metric view', () => {
    const out = importDesign('main.sales.Order_Revenue', yaml);
    expect(out.sources).toEqual(['cat.tpch.lineitem', 'cat.tpch.orders', 'cat.tpch.customer']);
    expect(out.name).toBe('order_revenue');
    expect(semanticBriefSchema.safeParse(out.brief).success).toBe(true);
    expect(out.brief.businessGoal).toBe('Revenue of wholesale orders');
    expect(out.brief.measures.map((m) => [m.name, m.aggregation])).toEqual([
      ['Net Revenue', 'sum'],
      ['Customers', 'count_distinct'],
    ]);
    expect(out.brief.timeGrains).toEqual([]);
    expect(out.tests.map((t) => t.name)).toEqual([
      'Net Revenue in total',
      'Net Revenue by Order Month',
      'Net Revenue by Customer Name',
    ]);
    expect(out.yaml).toBe(yaml);
  });

  it('refuses YAML that is not a valid metric view', () => {
    expect(() => importDesign('main.sales.x', 'version: 1.1\nsource: a.b.c\n')).toThrow(/not a valid metric view/);
  });
});
