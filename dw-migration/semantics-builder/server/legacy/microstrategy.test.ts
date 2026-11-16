import { describe, expect, it } from 'vitest';
import { validateMetricView } from '../../shared/metricView';
import { convertMicroStrategy, isMicroStrategy, translateMstr } from './microstrategy';

const t = (name: string, id = name) => ({ objectId: id, subType: 'logical_table', name });
const table = (name: string) => ({
  information: { objectId: name, subType: 'logical_table', name },
  physicalTable: { information: { name, subType: 'physical_table' }, namespace: 'dbo', tableName: name },
});
const expr = (text: string, ...tables: string[]) => ({ expression: { text }, tables: tables.map((n) => t(n)) });
const form = (id: string, name: string, category: string, lookup: string, ...expressions: object[]) => ({
  id,
  name,
  category,
  lookupTable: t(lookup),
  expressions,
});

const EXPORT = {
  tables: [table('ORDERS'), { information: { objectId: 'C1', subType: 'logical_table', name: 'CUSTOMER' } }],
  facts: [
    { information: { subType: 'fact', name: 'Total Price' }, expressions: [expr('O_TOTALPRICE', 'ORDERS')] },
    { information: { subType: 'fact', name: 'Discount' }, expressions: [expr('ApplySimple("#0", X)', 'ORDERS')] },
  ],
  attributes: [
    {
      information: { subType: 'attribute', name: 'Order' },
      forms: [form('f1', 'ID', 'ID', 'ORDERS', expr('O_ORDERKEY', 'ORDERS'))],
      keyForm: { id: 'f1' },
    },
    {
      information: { subType: 'attribute', name: 'Order Priority' },
      forms: [form('f2', 'ID', 'ID', 'ORDERS', expr('O_ORDERPRIORITY', 'ORDERS'))],
    },
    {
      information: { subType: 'attribute', name: 'Customer' },
      forms: [
        {
          ...form('f3', 'ID', 'ID', 'CUSTOMER', expr('O_CUSTKEY', 'ORDERS'), expr('C_CUSTKEY', 'CUSTOMER')),
          lookupTable: { objectId: 'C1' },
        },
        form('f4', 'DESC', 'DESC', 'CUSTOMER', expr('C_NAME', 'CUSTOMER')),
        form('f5', 'Segment', 'None', 'CUSTOMER', expr('C_MKTSEGMENT', 'CUSTOMER')),
      ],
      keyForm: { id: 'f3' },
      displays: { reportDisplays: [{ id: 'f4' }] },
    },
    {
      information: { subType: 'attribute', name: 'Nation' },
      forms: [form('f6', 'ID', 'ID', 'NATION', expr('N_NATIONKEY', 'NATION'))],
    },
  ],
  metrics: [
    { information: { subType: 'metric', name: 'Avg Order' }, expression: { text: 'Revenue / Orders' } },
    { information: { subType: 'metric', name: 'Revenue' }, expression: { text: 'Sum([Total Price]){~+}' } },
    { information: { subType: 'metric', name: 'Orders' }, expression: { text: 'Count<Distinct=True>(Order){~+}' } },
    {
      information: { subType: 'metric', name: 'Urgent Revenue' },
      expression: { text: "Sum(If([Order Priority] = '1-URGENT', [Total Price], 0))" },
    },
    { information: { subType: 'metric', name: 'Filtered' }, expression: { text: 'Sum([Total Price]) <[Urgent]>' } },
    { information: { subType: 'metric', name: 'Running' }, expression: { text: 'RunningSum(Revenue)' } },
  ],
};

describe('translateMstr', () => {
  const r = (n: string) => ({ X: 'x', Y: 'y' })[n] ?? null;
  it('translates functions, parameters and the report level, and stops on the rest', () => {
    expect(translateMstr('Sum(X){~+}', r)).toBe('SUM(x)');
    expect(translateMstr('Count<Distinct=True, UseLookupForAttributes=False>(X)', r)).toBe('COUNT(DISTINCT x)');
    expect(translateMstr('NullToZero(Sum(X)) / ZeroToNull(Sum(Y))', r)).toBe('COALESCE(SUM(x), 0) / NULLIF(SUM(y), 0)');
    expect(translateMstr('If(X > 1, Y, 0)', r)).toBe('CASE WHEN x > 1 THEN y ELSE 0 END');
    expect(translateMstr('Sum(X) {Year}', r)).toBeNull();
    expect(translateMstr('Sum(X) <[Filter]>', r)).toBeNull();
    expect(translateMstr('RunningSum(X)', r)).toBeNull();
    expect(translateMstr('Count<NullInclude=1>(X)', r)).toBeNull();
  });
});

describe('convertMicroStrategy', () => {
  const content = JSON.stringify(EXPORT);
  it('finds the export and builds a valid view with joins, dimensions and metrics', () => {
    expect(isMicroStrategy(content)).toBe(true);
    expect(isMicroStrategy('{"semantic_models": []}')).toBe(false);
    const r = convertMicroStrategy('project.json', content, 'samples.tpch', false);
    expect(r.view?.source).toBe('samples.tpch.orders');
    expect(r.view?.joins).toEqual([
      { name: 'customer_table', source: 'samples.tpch.customer', on: 'source.o_custkey = customer_table.c_custkey' },
    ]);
    const dims = Object.fromEntries(r.view!.dimensions.map((d) => [d.name, d.expr]));
    expect(dims).toEqual({
      Order: 'o_orderkey',
      'Order Priority': 'o_orderpriority',
      Customer: 'customer_table.c_name',
      'Customer Segment': 'customer_table.c_mktsegment',
    });
    // A measure comes after the measures it uses, as UC needs.
    expect(r.view!.measures.map((x) => x.name)).toEqual(['Revenue', 'Orders', 'Urgent Revenue', 'Avg Order']);
    const m = Object.fromEntries(r.view!.measures.map((x) => [x.name, x.expr]));
    expect(m).toEqual({
      'Avg Order': 'MEASURE(`Revenue`) / MEASURE(`Orders`)',
      Revenue: 'SUM(o_totalprice)',
      Orders: 'COUNT(DISTINCT o_orderkey)',
      'Urgent Revenue': "SUM(CASE WHEN o_orderpriority = '1-URGENT' THEN o_totalprice ELSE 0 END)",
    });
    expect(r.preview.fields.filter((f) => f.status === 'manual').map((f) => f.name)).toEqual([
      'Nation',
      'Filtered',
      'Running',
    ]);
    expect(r.todo.map((x) => x.name)).toEqual(['Filtered', 'Running']);
    expect(r.preview.issues.join(' ')).toMatch(/Discount/);
    expect(r.preview.issues.join(' ')).toMatch(/Nation does not join/);
    expect(validateMetricView(r.preview.yaml!).issues.filter((i) => i.severity === 'error')).toEqual([]);
  });

  it('uses the AI SQL for a metric with no rule, marked to check', () => {
    const r = convertMicroStrategy(
      'p.json',
      content,
      'samples.tpch',
      false,
      new Map([['Filtered', "SUM(o_totalprice) FILTER (WHERE o_orderpriority = '1-URGENT')"]])
    );
    expect(r.preview.fields.find((f) => f.name === 'Filtered')?.status).toBe('review');
  });

  it('asks for the catalog.schema, and refuses a file with no facts or metrics', () => {
    expect(convertMicroStrategy('p.json', content, undefined, false).preview.issues[0]).toMatch(/catalog\.schema/);
    expect(() => convertMicroStrategy('p.json', '{"information": {}}', undefined, false)).toThrow(/no MicroStrategy/);
  });
});
