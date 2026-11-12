import { describe, expect, it } from 'vitest';
import { validateMetricView } from '../../shared/metricView';
import { calculatedMeasures, convertSsas, isSsas, translateMdx } from './ssas';

const HEAD = '<?xml version="1.0" encoding="utf-8"?>';
const col = (name: string, extra = '') =>
  `<xs:element name="${name}" msprop:DbColumnName="${name}" ${extra} type="xs:string" />`;
const table = (id: string, db: string, cols: string) =>
  `<xs:element name="${id}" msprop:DbTableName="${db}" msprop:DbSchemaName="dbo" msprop:TableType="Table">
     <xs:complexType><xs:sequence>${cols}</xs:sequence></xs:complexType></xs:element>`;
const DSV = `${HEAD}
<DataSourceView xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><ID>TPCH</ID><Name>TPCH</Name>
  <Schema><xs:schema id="TPCH" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:msprop="urn:schemas-microsoft-com:xml-msprop">
    <xs:element name="TPCH"><xs:complexType><xs:choice>
      ${table('dbo_orders', 'ORDERS', col('O_ORDERKEY') + col('O_CUSTKEY') + col('O_TOTALPRICE') + col('O_ORDERPRIORITY') + '<xs:element name="Margin" msprop:ComputedColumnExpression="O_TOTALPRICE * 0.1" />')}
      ${table('dbo_customer', 'CUSTOMER', col('C_CUSTKEY') + col('C_NAME') + col('C_MKTSEGMENT'))}
    </xs:choice></xs:complexType></xs:element>
  </xs:schema></Schema>
</DataSourceView>`;
const bind = (t: string, c: string) =>
  `<Source xsi:type="ColumnBinding"><TableID>${t}</TableID><ColumnID>${c}</ColumnID></Source>`;
const attr = (id: string, key: string, t: string, extra = '') =>
  `<Attribute><ID>${id}</ID><Name>${id}</Name>${extra}<KeyColumns><KeyColumn><DataType>WChar</DataType>${bind(t, key)}</KeyColumn></KeyColumns></Attribute>`;
const CUSTOMER_DIM = `${HEAD}
<Dimension xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><ID>Dim Customer</ID><Name>Customer</Name>
  <Attributes>
    ${attr('Customer', 'C_CUSTKEY', 'dbo_customer', `<Usage>Key</Usage><NameColumn><DataType>WChar</DataType>${bind('dbo_customer', 'C_NAME')}</NameColumn>`)}
    ${attr('Market Segment', 'C_MKTSEGMENT', 'dbo_customer')}
    ${attr('Nation', 'N_NAME', 'dbo_nation')}
  </Attributes>
</Dimension>`;
const ORDER_DIM = `${HEAD}
<Dimension xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><ID>Dim Order</ID><Name>Order</Name>
  <Attributes>
    ${attr('Order', 'O_ORDERKEY', 'dbo_orders', '<Usage>Key</Usage>')}
    ${attr('Order Priority', 'O_ORDERPRIORITY', 'dbo_orders')}
  </Attributes>
</Dimension>`;
const measure = (name: string, agg: string, source: string) =>
  `<Measure><ID>${name}</ID><Name>${name}</Name><AggregateFunction>${agg}</AggregateFunction><Source><DataType>Double</DataType>${source}</Source></Measure>`;
const SCRIPT = `CALCULATE;
CREATE MEMBER CURRENTCUBE.[Measures].[Avg Order] AS [Measures].[Safe Avg] * 1, FORMAT_STRING = "Currency", VISIBLE = 1;
CREATE MEMBER CURRENTCUBE.[Measures].[Safe Avg] AS Divide([Measures].[Revenue], [Measures].[Order Count]);
CREATE MEMBER CURRENTCUBE.[Measures].[Big] AS 'IIF([Measures].[Revenue] > 1000, 1, 0)', VISIBLE = 0;
CREATE MEMBER CURRENTCUBE.[Measures].[Prior Revenue] AS ([Measures].[Revenue], [Date].[Calendar].PrevMember);`;
const CUBE = `${HEAD}
<Cube xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><ID>Sales</ID><Name>Sales</Name>
  <Dimensions>
    <Dimension><ID>Customer</ID><Name>Customer</Name><DimensionID>Dim Customer</DimensionID></Dimension>
    <Dimension><ID>Order</ID><Name>Order</Name><DimensionID>Dim Order</DimensionID></Dimension>
  </Dimensions>
  <MdxScripts><MdxScript><ID>MdxScript</ID><Commands><Command><Text>${SCRIPT.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')}</Text></Command></Commands></MdxScript></MdxScripts>
  <MeasureGroups>
    <MeasureGroup><ID>Orders</ID><Name>Orders</Name>
      <Measures>
        ${measure('Revenue', 'Sum', bind('dbo_orders', 'O_TOTALPRICE'))}
        ${measure('Order Count', 'Count', '<Source xsi:type="RowBinding"><TableID>dbo_orders</TableID></Source>')}
        ${measure('Customers', 'DistinctCount', bind('dbo_orders', 'O_CUSTKEY'))}
        ${measure('Last Price', 'LastNonEmpty', bind('dbo_orders', 'O_TOTALPRICE'))}
        ${measure('Margin', 'Sum', bind('dbo_orders', 'Margin'))}
      </Measures>
      <Dimensions>
        <Dimension xsi:type="RegularMeasureGroupDimension"><CubeDimensionID>Customer</CubeDimensionID>
          <Attributes><Attribute><AttributeID>Customer</AttributeID><KeyColumns><KeyColumn>${bind('dbo_orders', 'O_CUSTKEY')}</KeyColumn></KeyColumns><Type>Granularity</Type></Attribute></Attributes>
        </Dimension>
        <Dimension xsi:type="DegenerateMeasureGroupDimension"><CubeDimensionID>Order</CubeDimensionID></Dimension>
      </Dimensions>
    </MeasureGroup>
    <MeasureGroup><ID>Lines</ID><Name>Lines</Name><Measures>${measure('Quantity', 'Sum', bind('dbo_lineitem', 'L_QUANTITY'))}</Measures></MeasureGroup>
  </MeasureGroups>
</Cube>`;
const PROJECT = [DSV, CUSTOMER_DIM, ORDER_DIM, CUBE].join('\n');

describe('translateMdx', () => {
  const m = (n: string) => (['Revenue', 'Order Count'].includes(n) ? `MEASURE(\`${n}\`)` : null);
  it('translates arithmetic on measures, IIF and Divide, and stops on tuples and member functions', () => {
    expect(translateMdx('[Measures].[Revenue] / [Measures].[Order Count]', m)).toBe(
      'MEASURE(`Revenue`) / MEASURE(`Order Count`)'
    );
    expect(translateMdx('Divide([Revenue], [Order Count])', m)).toBe(
      'MEASURE(`Revenue`) / NULLIF(MEASURE(`Order Count`), 0)'
    );
    expect(translateMdx('IIF(IsEmpty([Revenue]), 0, [Revenue])', m)).toBe(
      'CASE WHEN (MEASURE(`Revenue`) IS NULL) THEN 0 ELSE MEASURE(`Revenue`) END'
    );
    expect(translateMdx('([Measures].[Revenue], [Date].[Calendar].PrevMember)', m)).toBeNull();
    expect(translateMdx('[Product].[Color].&[Red]', m)).toBeNull();
  });
  it('reads calculated measures from the MDX script', () => {
    expect(calculatedMeasures(SCRIPT).map((c) => [c.name, c.expr])).toEqual([
      ['Avg Order', '[Measures].[Safe Avg] * 1'],
      ['Safe Avg', 'Divide([Measures].[Revenue], [Measures].[Order Count])'],
      ['Big', 'IIF([Measures].[Revenue] > 1000, 1, 0)'],
      ['Prior Revenue', '([Measures].[Revenue], [Date].[Calendar].PrevMember)'],
    ]);
  });
});

describe('convertSsas', () => {
  it('finds the project files and builds a valid view', () => {
    expect(isSsas('3 files.ssas', PROJECT)).toBe(true);
    expect(isSsas('model.xml', '<querySubject/>')).toBe(false);
    const r = convertSsas('3 files.ssas', PROJECT, 'samples.tpch', false);
    expect(r.view?.source).toBe('samples.tpch.orders');
    // The join is named customer_table, because the dimension Customer has the name customer.
    expect(r.view?.joins).toEqual([
      { name: 'customer_table', source: 'samples.tpch.customer', on: 'source.o_custkey = customer_table.c_custkey' },
    ]);
    expect(Object.fromEntries(r.view!.dimensions.map((d) => [d.name, d.expr]))).toEqual({
      Customer: 'customer_table.c_name',
      'Market Segment': 'customer_table.c_mktsegment',
      'Order Priority': 'o_orderpriority',
    });
    expect(r.view!.measures.map((m) => [m.name, m.expr])).toEqual([
      ['Revenue', 'SUM(o_totalprice)'],
      ['Order Count', 'COUNT(1)'],
      ['Customers', 'COUNT(DISTINCT o_custkey)'],
      ['Safe Avg', 'MEASURE(`Revenue`) / NULLIF(MEASURE(`Order Count`), 0)'],
      ['Big', 'CASE WHEN MEASURE(`Revenue`) > 1000 THEN 1 ELSE 0 END'],
      ['Avg Order', 'MEASURE(`Safe Avg`) * 1'],
    ]);
    const manual = r.preview.fields.filter((f) => f.status === 'manual');
    expect(manual.map((f) => [f.name, f.note])).toEqual([
      ['Nation', 'On a snowflake table: a nested join.'],
      ['Last Price', 'A semi-additive measure (LastNonEmpty).'],
      ['Margin', 'A computed column or another table.'],
      ['Prior Revenue', 'An MDX expression with no rule, such as a tuple, a set or a time function.'],
    ]);
    expect(r.todo.map((t) => t.name)).toEqual(['Prior Revenue']);
    expect(r.preview.issues.join(' ')).toMatch(/measure group Lines is left out/);
    expect(validateMetricView(r.preview.yaml!).issues.filter((i) => i.severity === 'error')).toEqual([]);
  });

  it('uses the AI SQL for a calculated measure with no rule, and needs the catalog.schema', () => {
    const r = convertSsas('p.ssas', PROJECT, 'samples.tpch', false, new Map([['Prior Revenue', 'SUM(o_totalprice)']]));
    expect(r.preview.fields.find((f) => f.name === 'Prior Revenue')?.status).toBe('review');
    expect(convertSsas('p.ssas', PROJECT, undefined, false).preview.issues[0]).toMatch(/catalog\.schema/);
    expect(() => convertSsas('p.dim', ORDER_DIM, 'a.b', false)).toThrow(/no cube/);
  });
});
