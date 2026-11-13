import { describe, expect, it } from 'vitest';
import { validateMetricView } from '../../shared/metricView';
import { convertCognos, translateCognos } from './cognos';

const item = (name: string, usage: string, agg = 'total', ext = name) =>
  `<queryItem><name locale="en">${name}</name><externalName>${ext}</externalName><usage>${usage}</usage><regularAggregate>${agg}</regularAggregate></queryItem>`;
const bitem = (name: string, expr: string, usage: string, agg = 'total') =>
  `<queryItem><name locale="en">${name}</name><expression>${expr}</expression><usage>${usage}</usage><regularAggregate>${agg}</regularAggregate></queryItem>`;

const MODEL = `<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://www.developer.cognos.com/schemas/bmt/60/12">
  <name>Sales</name>
  <namespace><name>Model</name>
    <namespace><name>Database Layer</name>
      <querySubject><name>ORDERS</name>
        <definition><dbQuery><sources><dataSourceRef>[].[dataSources].[tpch]</dataSourceRef></sources>
          <sql type="cognos">Select * from [tpch].ORDERS</sql></dbQuery></definition>
        ${item('O_ORDERKEY', 'identifier', 'count')}
        ${item('O_CUSTKEY', 'identifier', 'count')}
        ${item('O_ORDERPRIORITY', 'attribute', 'count')}
        ${item('O_TOTALPRICE', 'fact')}
      </querySubject>
      <querySubject><name>CUSTOMER</name>
        <definition><dbQuery><sql type="cognos">Select * from [tpch].CUSTOMER</sql></dbQuery></definition>
        ${item('C_CUSTKEY', 'identifier', 'count')}
        ${item('C_MKTSEGMENT', 'attribute', 'count')}
      </querySubject>
      <relationship><name>ORDERS &lt;--&gt; CUSTOMER</name>
        <expression>[Database Layer].[ORDERS].[O_CUSTKEY] = [Database Layer].[CUSTOMER].[C_CUSTKEY]</expression>
        <left><refobj>[Database Layer].[ORDERS]</refobj><mincard>one</mincard><maxcard>many</maxcard></left>
        <right><refobj>[Database Layer].[CUSTOMER]</refobj><mincard>one</mincard><maxcard>one</maxcard></right>
      </relationship>
    </namespace>
    <namespace><name>Business Layer</name>
      <querySubject><name>Sales</name>
        <definition><modelQuery><sql type="cognos">Select ...</sql></modelQuery></definition>
        ${bitem('Order Priority', '[Database Layer].[ORDERS].[O_ORDERPRIORITY]', 'attribute', 'count')}
        ${bitem('Market Segment', '[Database Layer].[CUSTOMER].[C_MKTSEGMENT]', 'attribute', 'count')}
        ${bitem('Revenue', '[Database Layer].[ORDERS].[O_TOTALPRICE]', 'fact')}
        ${bitem('Urgent Revenue', "total(if ([Database Layer].[ORDERS].[O_ORDERPRIORITY] = '1-URGENT') then ([Database Layer].[ORDERS].[O_TOTALPRICE]) else (0))", 'fact')}
        ${bitem('Average Order', '[Business Layer].[Sales].[Revenue] / count(distinct [Database Layer].[ORDERS].[O_ORDERKEY])', 'fact')}
        ${bitem('Running Revenue', 'running-total([Database Layer].[ORDERS].[O_TOTALPRICE])', 'fact')}
      </querySubject>
    </namespace>
  </namespace>
</project>`;

describe('translateCognos', () => {
  const t = (e: string) => translateCognos(e, (p) => ({ A: 'a', B: 'b' })[p[p.length - 1]] ?? null);
  it('translates functions and if then else, and stops on macros and unknown functions', () => {
    expect(t('total([x].[A])')).toBe('SUM(a)');
    expect(t('if ([x].[A] > 1) then ([x].[B]) else (0)')).toBe('CASE WHEN (a > 1) THEN (b) ELSE (0) END');
    expect(t('if ([x].[A] > 1) then (1) else (if ([x].[B] = 2) then (2) else (3))')).toBe(
      'CASE WHEN (a > 1) THEN (1) ELSE (CASE WHEN (b = 2) THEN (2) ELSE (3) END) END'
    );
    expect(t('count(distinct [x].[A])')).toBe('COUNT(DISTINCT a)');
    expect(t("#prompt('p')#")).toBeNull();
    expect(t('running-total([x].[A])')).toBeNull();
  });
});

describe('convertCognos', () => {
  const r = convertCognos('model.xml', MODEL, 'sandbox_source.tpch', false);
  const expr = Object.fromEntries([...r.view!.dimensions, ...r.view!.measures].map((f) => [f.name, f.expr]));

  it('makes a valid metric view from the database layer and its relationship', () => {
    expect(r.preview.sources).toEqual(['sandbox_source.tpch.orders', 'sandbox_source.tpch.customer']);
    expect(r.view!.joins).toEqual([
      { name: 'customer', source: 'sandbox_source.tpch.customer', on: 'source.o_custkey = customer.c_custkey' },
    ]);
    expect(validateMetricView(r.preview.yaml!).issues.filter((i) => i.severity === 'error')).toEqual([]);
  });

  it('takes the fields from the business layer', () => {
    expect(expr).toMatchObject({
      'Order Priority': 'o_orderpriority',
      'Market Segment': 'customer.c_mktsegment',
      Revenue: 'SUM(o_totalprice)',
      'Urgent Revenue': "SUM(CASE WHEN (o_orderpriority = '1-URGENT') THEN (o_totalprice) ELSE (0) END)",
      'Average Order': 'MEASURE(`Revenue`) / COUNT(DISTINCT o_orderkey)',
    });
    expect(r.preview.fields.find((f) => f.name === 'Running Revenue')?.status).toBe('manual');
    expect(r.todo.map((x) => x.name)).toEqual(['Running Revenue']);
  });

  it('renames a join that has the name of a field', () => {
    const m = convertCognos(
      'model.xml',
      MODEL.replace('<name locale="en">Market Segment</name>', '<name locale="en">Customer</name>'),
      'sandbox_source.tpch',
      false
    );
    expect(m.view!.joins![0].name).toBe('customer_table');
    expect(m.view!.dimensions.find((d) => d.name === 'Customer')?.expr).toBe('customer_table.c_mktsegment');
  });
});
