import { describe, expect, it } from 'vitest';
import { validateMetricView } from '../../shared/metricView';
import { convertTabular } from './tabular';
import { zipOf } from './zip.fixture';

const dbx = (c: string, s: string, t: string) => [
  'let',
  '  Source = Databricks.Catalogs("adb-1.azuredatabricks.net", "/sql/1.0/warehouses/x", []),',
  `  c = Source{[Name="${c}",Kind="Database"]}[Data],`,
  `  s = c{[Name="${s}",Kind="Schema"]}[Data],`,
  `  t = s{[Name="${t}",Kind="Table"]}[Data]`,
  'in t',
];
const BIM = {
  name: 'Sales model',
  compatibilityLevel: 1600,
  model: {
    tables: [
      {
        name: 'Orders',
        columns: [
          { name: 'OrderKey', dataType: 'int64', sourceColumn: 'o_orderkey', isHidden: true },
          { name: 'CustKey', dataType: 'int64', sourceColumn: 'o_custkey' },
          { name: 'Priority', dataType: 'string', sourceColumn: 'o_orderpriority' },
          { name: 'Order Date', dataType: 'dateTime', sourceColumn: 'o_orderdate' },
          { name: 'Price', dataType: 'decimal', sourceColumn: 'o_totalprice' },
          { name: 'Big', dataType: 'boolean', type: 'calculated', expression: 'Orders[Price] > 100000' },
        ],
        measures: [
          { name: 'Average Price', expression: 'DIVIDE([Total Price], [Order Count])' },
          { name: 'Total Price', expression: 'SUM(Orders[Price])', description: 'Sum of the price.' },
          { name: 'Order Count', expression: 'COUNTROWS(Orders)' },
          { name: 'Urgent Price', expression: 'CALCULATE(SUM(Orders[Price]), Orders[Priority] = "1-URGENT")' },
          { name: 'Price YTD', expression: 'TOTALYTD([Total Price], Orders[Order Date])' },
        ],
        partitions: [{ source: { type: 'm', expression: dbx('sandbox_source', 'tpch', 'orders') } }],
      },
      {
        name: 'Customer',
        columns: [
          { name: 'CustKey', dataType: 'int64', sourceColumn: 'c_custkey' },
          { name: 'Segment', dataType: 'string', sourceColumn: 'c_mktsegment' },
          { name: 'Price', dataType: 'string', sourceColumn: 'c_phone' },
        ],
        partitions: [
          {
            source: {
              type: 'm',
              expression: ['let Source = Sql.Database("srv", "db"){[Schema="dbo",Item="customer"]}[Data] in Source'],
            },
          },
        ],
      },
      {
        name: 'Report Measures',
        columns: [],
        measures: [{ name: 'Segments', expression: 'DISTINCTCOUNT(Customer[Segment])' }],
      },
    ],
    relationships: [
      { name: 'r1', fromTable: 'Orders', fromColumn: 'CustKey', toTable: 'Customer', toColumn: 'CustKey' },
    ],
  },
};

describe('convertTabular', () => {
  const r = convertTabular('model.bim', JSON.stringify(BIM), 'sandbox_source.tpch', false);
  const status = Object.fromEntries(r.preview.fields.map((f) => [f.name, f.status]));
  const expr = Object.fromEntries([...r.view!.dimensions, ...r.view!.measures].map((f) => [f.name, f.expr]));

  it('makes a valid metric view on the fact, with tables from the Databricks connector', () => {
    expect(r.preview.sources).toEqual(['sandbox_source.tpch.orders', 'sandbox_source.tpch.customer']);
    expect(r.view!.joins).toEqual([
      { name: 'customer', source: 'sandbox_source.tpch.customer', on: 'source.o_custkey = customer.c_custkey' },
    ]);
    expect(r.preview.issues).toEqual(['Customer was mapped by name to sandbox_source.tpch.customer. Check it.']);
    expect(validateMetricView(r.preview.yaml!).issues.filter((i) => i.severity === 'error')).toEqual([]);
  });

  it('translates DAX by rules in any order, and leaves the rest for the AI', () => {
    expect(expr['Total Price']).toBe('SUM(o_totalprice)');
    expect(expr['Average Price']).toBe('MEASURE(`Total Price`) / NULLIF(MEASURE(`Order Count`), 0)');
    expect(expr['Urgent Price']).toBe("SUM(o_totalprice) FILTER (WHERE o_orderpriority = '1-URGENT')");
    expect(expr.Segments).toBe('COUNT(DISTINCT customer.c_mktsegment)');
    expect(expr.Segment).toBe('customer.c_mktsegment');
    // A column with the name of a measure is renamed; numeric value columns are not dimensions.
    expect(expr['Price 2']).toBe('customer.c_phone');
    expect(Object.keys(expr)).not.toContain('Price');
    expect(status).toMatchObject({ 'Price YTD': 'manual', Big: 'manual', Priority: 'converted' });
    expect(r.todo).toEqual([{ name: 'Price YTD', dax: 'TOTALYTD([Total Price], Orders[Order Date])' }]);
  });

  it('marks AI SQL to check, and reads the model of a .pbit template', () => {
    const ai = convertTabular(
      'model.bim',
      JSON.stringify(BIM),
      'sandbox_source.tpch',
      false,
      new Map([['Price YTD', 'SUM(o_totalprice)']])
    );
    expect(ai.preview.fields.find((f) => f.name === 'Price YTD')).toMatchObject({ status: 'review' });
    const utf16 = Buffer.concat([Buffer.from([0xff, 0xfe]), Buffer.from(JSON.stringify(BIM), 'utf16le')]);
    const pbit = zipOf('DataModelSchema', utf16).toString('base64');
    expect(convertTabular('Sales.pbit', pbit, 'sandbox_source.tpch', true).preview.yaml).toBe(r.preview.yaml);
    expect(() => convertTabular('x.bim', '{"model":{}}', undefined, false)).toThrow(/no model tables/);
  });
});
