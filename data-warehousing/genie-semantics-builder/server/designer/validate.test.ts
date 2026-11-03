import { afterEach, describe, expect, it } from 'vitest';
import { validateMetricView } from '../../shared/metricView';
import { checkStatement } from '../sql/allowlist';
import { compareRows, createStatement, expandedQuery, measureQuery, sandboxSchema, sandboxViewName } from './validate';

const YAML = `version: 1.1
source: s.t.lineitem
filter: source.l_shipdate >= '2020-01-01'
joins:
  - name: dim_orders
    source: s.t.orders
    'on': source.l_orderkey = dim_orders.o_orderkey
    joins:
      - name: customer
        source: s.t.customer
        'on': dim_orders.o_custkey = customer.c_custkey
dimensions:
  - name: Segment
    expr: dim_orders.customer.c_mktsegment
  - name: Label
    expr: "CONCAT('dim_orders.customer.x', dim_orders.customer.c_name)"
measures:
  - name: Net Revenue
    expr: SUM(source.l_extendedprice * (1 - source.l_discount))
  - name: Orders
    expr: COUNT(DISTINCT source.l_orderkey)
  - name: AOV
    expr: MEASURE(\`Net Revenue\`) / MEASURE(Orders)
`;
const view = validateMetricView(YAML).view!;

afterEach(() => delete process.env.GSB_SANDBOX_SCHEMA);

describe('validation', () => {
  it('reads the sandbox schema only from valid config', () => {
    expect(sandboxSchema()).toBeNull();
    process.env.GSB_SANDBOX_SCHEMA = 'sandbox.gsb';
    expect(sandboxSchema()).toBe('sandbox.gsb');
    process.env.GSB_SANDBOX_SCHEMA = 'a.b.c';
    expect(sandboxSchema()).toBeNull();
    expect(sandboxViewName('sandbox.gsb', 'sales', '47d9362a-39c6-4a4d')).toBe('sandbox.gsb.sales__gsb_47d9362a');
  });

  it('builds an allowlisted CREATE and refuses $$ in the YAML', () => {
    const sql = createStatement('sandbox.gsb.sales__gsb_1', `${YAML}-- a comment; DROP TABLE x\n`);
    expect(checkStatement(sql).kind).toBe('ddl');
    expect(
      sql.startsWith('CREATE OR REPLACE VIEW `sandbox`.`gsb`.`sales__gsb_1` WITH METRICS LANGUAGE YAML AS $$\n')
    ).toBe(true);
    expect(() => createStatement('a.b.c', 'x: $$; DROP TABLE y')).toThrow(/\$\$/);
  });

  it('builds read-only test queries', () => {
    const test = { name: 't', dimensions: ['Segment'], measures: ['AOV'] };
    const mq = measureQuery('sandbox.gsb.v', test);
    expect(mq).toBe(
      'SELECT `Segment`, MEASURE(`AOV`) AS `AOV` FROM `sandbox`.`gsb`.`v` GROUP BY ALL ORDER BY ALL LIMIT 1001'
    );
    const eq = expandedQuery(view, test)!;
    expect(eq).toBe(
      [
        'SELECT (customer.c_mktsegment) AS `Segment`, ((SUM(source.l_extendedprice * (1 - source.l_discount))) / (COUNT(DISTINCT source.l_orderkey))) AS `AOV`',
        'FROM `s`.`t`.`lineitem` AS source',
        'LEFT JOIN `s`.`t`.`orders` AS `dim_orders` ON source.l_orderkey = dim_orders.o_orderkey',
        'LEFT JOIN `s`.`t`.`customer` AS `customer` ON dim_orders.o_custkey = customer.c_custkey',
        "WHERE source.l_shipdate >= '2020-01-01'",
        'GROUP BY ALL',
        'ORDER BY ALL LIMIT 1001',
      ].join('\n')
    );
    expect(checkStatement(mq).kind).toBe('read');
    expect(checkStatement(eq).kind).toBe('read');
    expect(expandedQuery(view, { name: 'l', dimensions: ['Label'], measures: ['Orders'] })).toContain(
      "(CONCAT('dim_orders.customer.x', customer.c_name)) AS `Label`"
    );
    expect(expandedQuery(view, { name: 'total', dimensions: [], measures: ['Orders'] })).not.toContain('GROUP BY');
    const ranked = validateMetricView(
      YAML.replace('  - name: AOV\n', '  - name: Rank\n    expr: RANK() OVER (ORDER BY SUM(source.l_tax))\n$&')
    ).view!;
    expect(expandedQuery(ranked, { name: 'r', dimensions: ['Segment'], measures: ['Rank'] })).toBeNull();
  });

  it('compares rows with a numeric tolerance and hides values', () => {
    expect(compareRows(['a', 'b'], [['x', '1.0000000001']], [['x', '1']])).toMatchObject({ status: 'passed', rows: 1 });
    expect(compareRows(['a', 'b'], [['x', '2']], [['x', '1']])).toEqual({
      status: 'failed',
      rows: 1,
      detail: 'Row 1, column b differs from plain SQL.',
    });
    expect(compareRows(['a'], [['x'], ['y']], [['x']]).status).toBe('failed');
    expect(compareRows(['a'], [[null]], [['0']]).status).toBe('failed');
  });
});
