import { describe, expect, it } from 'vitest';
import { renderMetricView, validateMetricView } from './metricView';
import type { SourceProfiles } from './metricView';

const table = (columns: string[], primaryKey: string[] = []) => ({
  columns: columns.map((name) => ({ name })),
  primaryKey,
});

const profiles: SourceProfiles = {
  'samples.tpch.lineitem': table(['l_orderkey', 'l_linenumber', 'l_extendedprice', 'l_discount', 'l_tax']),
  'samples.tpch.orders': table(['o_orderkey', 'o_custkey', 'o_orderdate'], ['o_orderkey']),
  'samples.tpch.customer': table(['c_custkey', 'c_nationkey', 'c_mktsegment'], ['c_custkey']),
  'samples.tpch.nation': table(['n_nationkey', 'n_name', 'n_regionkey'], ['n_nationkey']),
  'samples.tpch.region': table(['r_regionkey', 'r_name'], ['r_regionkey']),
};

const GOLDEN = `version: 1.1
source: samples.tpch.lineitem
comment: Net revenue by order month, market segment, nation and region.
joins:
  - name: dim_orders
    source: samples.tpch.orders
    'on': source.l_orderkey = dim_orders.o_orderkey
    joins:
      - name: customer
        source: samples.tpch.customer
        'on': dim_orders.o_custkey = customer.c_custkey
        joins:
          - name: nation
            source: samples.tpch.nation
            'on': customer.c_nationkey = nation.n_nationkey
            joins:
              - name: region
                source: samples.tpch.region
                'on': nation.n_regionkey = region.r_regionkey
dimensions:
  - name: Order Month
    expr: "DATE_TRUNC('MONTH', dim_orders.o_orderdate)"
    display_name: Order month
    format:
      type: date
      date_format: year_month_day
  - name: Market Segment
    expr: dim_orders.customer.c_mktsegment
    synonyms: [segment]
  - name: Nation
    expr: dim_orders.customer.nation.n_name
  - name: Region
    expr: dim_orders.customer.nation.region.r_name
measures:
  - name: Net Revenue
    expr: SUM(source.l_extendedprice * (1 - source.l_discount))
    format:
      type: currency
      currency_code: USD
      decimal_places: { type: exact, places: 2 }
  - name: Order Count
    expr: COUNT(DISTINCT source.l_orderkey)
  - name: Average Order Value
    expr: MEASURE(\`Net Revenue\`) / MEASURE(\`Order Count\`)
`;

const errors = (yaml: string) => validateMetricView(yaml, profiles).issues.filter((i) => i.severity === 'error');
const lineOf = (yaml: string, needle: string) => yaml.split('\n').findIndex((l) => l.includes(needle)) + 1;

describe('validateMetricView', () => {
  it('accepts the TPC-H snowflake model without issues', () => {
    const { view, issues } = validateMetricView(GOLDEN, profiles);
    expect(issues).toEqual([]);
    expect(view?.version).toBe('1.1');
    expect(view?.joins?.[0]?.joins?.[0]?.joins?.[0]?.name).toBe('nation');
  });

  it('round-trips through render with the on key quoted', () => {
    const view = validateMetricView(GOLDEN, profiles).view;
    expect(view).toBeDefined();
    const yaml = renderMetricView(view!);
    expect(yaml).toMatch(/^\s*["']on["']:/m);
    expect(yaml).toMatch(/^version: "1\.1"$/m);
    expect(validateMetricView(yaml, profiles)).toEqual({ view, issues: [] });
  });

  it('quotes values that YAML would misread', () => {
    const view = validateMetricView(GOLDEN, profiles).view!;
    const tricky = {
      ...view,
      dimensions: [
        { name: 'Flag', expr: '`weird col`' },
        { name: 'yes', expr: 'a: b' },
      ],
    };
    expect(validateMetricView(renderMetricView(tricky)).view?.dimensions).toEqual(tricky.dimensions);
  });

  it('reports YAML syntax errors with a line', () => {
    const [issue] = errors('source: a.b.c\ndimensions:\n  - name: [x\n');
    expect(issue?.line).toBeGreaterThan(0);
  });

  it('explains an unquoted on key', () => {
    const yaml = GOLDEN.replace("'on': source.l_orderkey", 'on: source.l_orderkey');
    expect(errors(yaml)).toEqual([expect.objectContaining({ message: "Quote the join key as 'on':", line: 5 })]);
  });

  it('requires a format type', () => {
    const yaml = GOLDEN.replace('      type: date\n', '');
    expect(errors(yaml)[0]).toMatchObject({ line: lineOf(yaml, 'format:') });
  });

  it('rejects a join with both on and using', () => {
    const yaml = GOLDEN.replace("    'on': source.l_orderkey = dim_orders.o_orderkey\n", '$&    using: [o_orderkey]\n');
    expect(errors(yaml)[0]?.message).toMatch(/exactly one of on or using/);
  });

  it('checks MEASURE references', () => {
    const yaml = GOLDEN.replace('MEASURE(`Order Count`)', 'MEASURE(`Orders`)');
    expect(errors(yaml)).toEqual([
      expect.objectContaining({ message: 'MEASURE(`Orders`) does not match a measure', line: lineOf(yaml, 'Orders') }),
    ]);
  });

  it('requires the full join path for nested tables', () => {
    const yaml = GOLDEN.replace('dim_orders.customer.nation.n_name', 'nation.n_name');
    expect(errors(yaml)[0]?.message).toBe(
      'Use the full join path dim_orders.customer.nation.n_name instead of nation.n_name'
    );
  });

  it('checks columns against the profiles', () => {
    const yaml = GOLDEN.replace('dim_orders.customer.c_mktsegment', 'dim_orders.customer.c_segment');
    expect(errors(yaml)[0]).toMatchObject({
      message: 'Column c_segment does not exist in dim_orders.customer (samples.tpch.customer)',
      line: lineOf(yaml, 'c_segment'),
    });
    expect(errors(GOLDEN.replace('source.l_tax', 'x').replace('l_discount))', 'l_discountt))'))[0]?.message).toMatch(
      /l_discountt does not exist in source/
    );
  });

  it('ignores names inside string literals', () => {
    expect(errors(GOLDEN.replace("'MONTH'", "'nation.n_name'"))).toEqual([]);
  });

  it('rejects duplicate names', () => {
    const dup = GOLDEN.replace('name: Region', 'name: Nation');
    expect(errors(dup)[0]?.message).toMatch(/already used/);
  });

  it('accepts the current spec: fields, rely, cardinality, window offset and AGG', () => {
    const current = GOLDEN.replace('dimensions:', 'fields:')
      .replace("    'on': source.l_orderkey = dim_orders.o_orderkey\n", '$&    rely:\n      at_most_one_match: true\n')
      .replace(
        '    expr: COUNT(DISTINCT source.l_orderkey)\n',
        '$&    window:\n      - order: Order Month\n        range: trailing 3 month exclusive\n        offset: -1 month\n'
      )
      .replace('MEASURE(`Order Count`)', 'AGG(`Order Count`)');
    const noPk = { ...profiles, 'samples.tpch.orders': table(['o_orderkey', 'o_custkey', 'o_orderdate']) };
    const { view, issues } = validateMetricView(current, noPk);
    expect(issues).toEqual([]);
    expect(view?.dimensions).toHaveLength(4);
    expect(renderMetricView(view!)).toMatch(/^fields:$/m);
    const bad = current.replace('MEASURE(`Net Revenue`)', 'MEASURE(`Nope`)');
    expect(errors(bad)[0]?.line).toBe(lineOf(bad, 'Nope'));
    const badField = current.replace('expr: dim_orders.customer.c_mktsegment', 'expr: ""');
    expect(errors(badField)[0]?.line).toBe(lineOf(badField, 'expr: ""'));
  });

  it('warns when a join may fan out', () => {
    const noPk = { ...profiles, 'samples.tpch.orders': table(['o_orderkey', 'o_custkey', 'o_orderdate']) };
    const [issue, ...rest] = validateMetricView(GOLDEN, noPk).issues;
    expect(rest).toEqual([]);
    expect(issue).toMatchObject({ severity: 'warning' });
    expect(issue?.message).toMatch(/declares no primary key/);
    const wrongKey = GOLDEN.replace('= customer.c_custkey', '= customer.c_nationkey');
    expect(validateMetricView(wrongKey, profiles).issues[0]?.message).toMatch(/do not cover the primary key/);
  });

  it('rejects a measure that uses a join name that is also a field name', () => {
    const clash = GOLDEN.replace('name: Nation\n', 'name: Dim_Orders\n').replace(
      'COUNT(DISTINCT source.l_orderkey)',
      'COUNT(DISTINCT dim_orders.o_orderkey)'
    );
    expect(errors(clash)[0]?.message).toMatch(/is a field and a join name/);
    expect(errors(GOLDEN.replace('name: Nation\n', 'name: Customer\n'))).toEqual([]);
  });

  it('accepts ranking window functions and partition measures with a warning', () => {
    const extra = GOLDEN.replace(
      '  - name: Order Count\n',
      `  - name: Revenue Rank
    expr: RANK() OVER (PARTITION BY \`Region\` ORDER BY SUM(source.l_extendedprice) DESC)
  - name: Avg Orders per Month
    expr: COUNT(DISTINCT source.l_orderkey)
    partition:
      include: [Order Month]
      outer_aggregate: avg
$&`
    );
    const { view, issues } = validateMetricView(extra, profiles);
    expect(issues.map((i) => [i.severity, i.message])).toEqual([
      ['warning', expect.stringMatching(/partition is not in the documented spec/)],
    ]);
    expect(renderMetricView(view!)).toMatch(/outer_aggregate: avg/);
    const badRef = extra.replace('include: [Order Month]', 'include: [Nope]');
    expect(errors(badRef)[0]?.message).toMatch(/Partition field "Nope" is not a dimension/);
  });
});
