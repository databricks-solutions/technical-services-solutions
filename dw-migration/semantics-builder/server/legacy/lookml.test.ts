import { describe, expect, it } from 'vitest';
import { validateMetricView } from '../../shared/metricView';
import { convertLookml, parseLookml } from './lookml';

const LKML = `
# orders.view.lkml
view: orders {
  sql_table_name: tpch.orders ;;
  dimension: id { primary_key: yes type: number sql: \${TABLE}.o_orderkey ;; }
  dimension: customer_id { type: number hidden: yes sql: \${TABLE}.o_custkey ;; }
  dimension: priority { label: "Order Priority" type: string sql: \${TABLE}.o_orderpriority ;; }
  dimension: amount { type: number hidden: yes sql: \${TABLE}.o_totalprice ;; }
  dimension: is_big { type: yesno sql: \${amount} > 100000 ;; }
  dimension: in_region { type: string sql: {% if x %} 1 {% endif %} ;; }
  dimension_group: ordered { type: time timeframes: [raw, date, month, year] sql: \${TABLE}.o_orderdate ;; }
  measure: count { type: count }
  measure: total_value { type: sum sql: \${amount} ;; description: "Sum of order value." }
  measure: urgent_value { type: sum sql: \${amount} ;; filters: [priority: "1-URGENT"] }
  measure: not_urgent { type: sum sql: \${amount} ;; filters: [priority: "-1-URGENT"] }
  measure: average_value { type: number sql: \${total_value} / NULLIF(\${count}, 0) ;; }
  measure: buyers { type: count_distinct sql: \${customer_id} ;; }
  measure: odd { type: list list_field: priority }
}
view: customer {
  sql_table_name: sandbox_source.tpch.customer ;;
  dimension: id { primary_key: yes sql: \${TABLE}.c_custkey ;; }
  dimension: segment { sql: \${TABLE}.c_mktsegment ;; }
  measure: balance { type: sum sql: \${TABLE}.c_acctbal ;; }
}
explore: orders {
  join: customer {
    type: left_outer
    relationship: many_to_one
    sql_on: \${orders.customer_id} = \${customer.id} ;;
  }
}
`;

describe('parseLookml', () => {
  it('reads blocks, lists, strings and ;; SQL, and stops on a syntax error', () => {
    const top = parseLookml('view: a { dimension: b { sql: x ;; label: "B" timeframes: [date, month] } }');
    expect(top).toEqual([
      {
        key: 'view',
        name: 'a',
        value: [
          {
            key: 'dimension',
            name: 'b',
            value: [
              { key: 'sql', value: 'x' },
              { key: 'label', value: 'B' },
              { key: 'timeframes', value: ['date', 'month'] },
            ],
          },
        ],
      },
    ]);
    expect(() => parseLookml('view: a { sql: x ')).toThrow(/does not end with ;;/);
    expect(() => parseLookml('view: a { b: "c }')).toThrow(/string does not end/);
  });
});

describe('convertLookml', () => {
  const r = convertLookml('model.lkml', LKML, 'sandbox_source.tpch');
  const status = Object.fromEntries(r.preview.fields.map((f) => [f.name, f.status]));
  const expr = Object.fromEntries([...r.view!.dimensions, ...r.view!.measures].map((f) => [f.name, f.expr]));

  it('makes a valid metric view on the explore, with its join', () => {
    expect(r.preview.sources).toEqual(['sandbox_source.tpch.orders', 'sandbox_source.tpch.customer']);
    expect(r.view!.joins).toEqual([
      { name: 'customer', source: 'sandbox_source.tpch.customer', on: 'source.o_custkey = customer.c_custkey' },
    ]);
    expect(r.preview.issues).toEqual([]);
    expect(validateMetricView(r.preview.yaml!).issues.filter((i) => i.severity === 'error')).toEqual([]);
  });

  it('converts fields by their type, and marks what a person must check or do', () => {
    expect(expr['Order Priority']).toBe('o_orderpriority');
    expect(expr['Is Big']).toBe('o_totalprice > 100000');
    expect(expr['Ordered Month']).toBe("DATE_TRUNC('MONTH', o_orderdate)");
    expect(expr.Segment).toBe('customer.c_mktsegment');
    expect(expr.Count).toBe('COUNT(1)');
    expect(expr['Urgent Value']).toBe("SUM(o_totalprice) FILTER (WHERE o_orderpriority = '1-URGENT')");
    expect(expr['Average Value']).toBe('MEASURE(`Total Value`) / NULLIF(MEASURE(`Count`), 0)');
    expect(expr.Buyers).toBe('COUNT(DISTINCT o_custkey)');
    expect(expr.Balance).toBe('SUM(customer.c_acctbal)');
    expect(status).toMatchObject({
      'In Region': 'manual',
      'Not Urgent': 'manual',
      Odd: 'manual',
      Balance: 'review',
      'Total Value': 'converted',
    });
    expect(Object.keys(expr)).not.toContain('Amount');
    expect(Object.keys(expr)).not.toContain('Id');
    expect(r.view!.measures.find((m) => m.name === 'Total Value')?.comment).toBe('Sum of order value.');
  });

  it('asks for a schema when a table name is short', () => {
    expect(convertLookml('m.lkml', LKML).preview.issues[0]).toMatch(/catalog.schema/);
    expect(() => convertLookml('m.lkml', 'explore: x {}')).toThrow(/no view/);
  });
});
