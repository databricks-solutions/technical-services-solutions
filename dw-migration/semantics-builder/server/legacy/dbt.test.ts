import { describe, expect, it } from 'vitest';
import { validateMetricView } from '../../shared/metricView';
import { convertDbt } from './dbt';

const YAML = `
semantic_models:
  - name: orders
    model: ref('orders')
    description: One row per order.
    defaults: { agg_time_dimension: ordered_at }
    entities:
      - { name: order_id, type: primary }
      - { name: customer, type: foreign, expr: customer_id }
    dimensions:
      - { name: ordered_at, type: time, type_params: { time_granularity: day } }
      - { name: status, type: categorical }
      - { name: is_large, type: categorical, expr: "order_total > 100" }
    measures:
      - { name: order_total, agg: sum, expr: amount }
      - { name: order_count, agg: sum, expr: 1 }
      - { name: customers_with_orders, agg: count_distinct, expr: customer_id }
      - { name: p90_order, agg: percentile, expr: amount, agg_params: { percentile: 0.9 } }
  - name: customers
    model: ref('customers')
    entities:
      - { name: customer, type: primary, expr: customer_id }
    dimensions:
      - { name: region, type: categorical }
      - { name: full_name, type: categorical, expr: "first_name || ' ' || last_name" }
  - name: stores
    model: ref('stores')
    entities:
      - { name: store, type: primary, expr: store_id }
metrics:
  - name: revenue
    label: Revenue
    type: simple
    type_params: { measure: order_total }
  - name: completed_revenue
    type: simple
    type_params: { measure: order_total }
    filter: "{{ Dimension('order_id__status') }} = 'completed'"
  - name: orders
    type: simple
    type_params: { measure: order_count }
  - name: average_order_value
    type: ratio
    type_params: { numerator: revenue, denominator: orders }
  - name: revenue_minus_completed
    type: derived
    type_params:
      expr: rev - done
      metrics: [{ name: revenue, alias: rev }, { name: completed_revenue, alias: done }]
  - name: revenue_growth
    type: derived
    type_params:
      expr: revenue - last_year
      metrics: [revenue, { name: revenue, alias: last_year, offset_window: 1 year }]
  - name: cumulative_revenue
    type: cumulative
    type_params: { measure: order_total, window: 7 days }
  - name: p90
    type: simple
    type_params: { measure: p90_order }
  - name: odd
    type: simple
    type_params: { measure: order_total }
    filter: "{{ TimeDimension('metric_time', 'day') }} > '2024-01-01'"
`;

describe('convertDbt', () => {
  const r = convertDbt('semantic_models.yml', YAML, 'main.jaffle');
  const status = Object.fromEntries(r.preview.fields.map((f) => [f.name, f.status]));

  it('makes a valid metric view on the fact, joined to the models of its foreign entities', () => {
    expect(r.preview.sources).toEqual(['main.jaffle.orders', 'main.jaffle.customers']);
    expect(r.preview.issues).toEqual(['stores does not join to orders by an entity, so its fields are left out.']);
    expect(validateMetricView(r.preview.yaml!).issues.filter((i) => i.severity === 'error')).toEqual([]);
    expect(r.view!.joins).toEqual([
      { name: 'customers', source: 'main.jaffle.customers', on: 'source.customer_id = customers.customer_id' },
    ]);
  });

  it('converts each metric by its type, and marks what a person must check or do', () => {
    const expr = Object.fromEntries(r.view!.measures.map((m) => [m.name, m.expr]));
    expect(expr.Revenue).toBe('SUM(amount)');
    expect(expr['Completed Revenue']).toBe("SUM(amount) FILTER (WHERE status = 'completed')");
    expect(expr['Average Order Value']).toBe('MEASURE(`Revenue`) / NULLIF(MEASURE(`Orders`), 0)');
    expect(expr['Revenue Minus Completed']).toBe('MEASURE(`Revenue`) - MEASURE(`Completed Revenue`)');
    expect(expr.P90).toBe('PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY amount)');
    expect(status).toMatchObject({
      Revenue: 'converted',
      'Average Order Value': 'converted',
      'Revenue Minus Completed': 'review',
      P90: 'review',
      'Revenue Growth': 'manual',
      'Cumulative Revenue': 'manual',
      Odd: 'manual',
      Region: 'converted',
      'Full Name': 'manual',
    });
    expect(r.view!.dimensions.find((d) => d.name === 'Region')).toMatchObject({
      expr: 'customers.region',
      synonyms: ['region'],
    });
    expect(r.explanations.measures.Revenue.explanation).toMatch(/^From dbt \(converted\): revenue \(simple\)/);
    expect(r.explanations.summary).toMatch(/converted, 2 to check, 4 not converted\.$/);
  });

  it('reads the tables of a manifest, and asks for a schema when YAML uses ref()', () => {
    const manifest = JSON.stringify({
      semantic_models: [
        {
          name: 'orders',
          node_relation: { database: 'prod', schema_name: 'gold', alias: 'fct_orders' },
          measures: [{ name: 'order_total', agg: 'sum', expr: 'amount' }],
        },
      ],
      metrics: [],
    });
    expect(convertDbt('semantic_manifest.json', manifest).preview.sources).toEqual(['prod.gold.fct_orders']);
    expect(convertDbt('m.yml', YAML).preview.issues[0]).toMatch(/Type the catalog.schema/);
    expect(() => convertDbt('x.yml', 'models: []')).toThrow(/no semantic_models/);
  });
});
