import { describe, expect, it } from 'vitest';
import { validateMetricView } from '../../shared/metricView';
import { convertTabular } from './tabular';
import { parseTmdl } from './tmdl';

const ORDERS = `/// Orders of the wholesale business
table Orders
	lineageTag: 1b2c

	measure Revenue = SUM(Orders[o_totalprice])
		formatString: #,0
		lineageTag: 3d4e

	/// Revenue of urgent orders
	measure 'Urgent Revenue' =
			CALCULATE(
				SUM(Orders[o_totalprice]),
				Orders[Order Priority] = "1-URGENT"
			)
		lineageTag: 5f6a

	measure 'Revenue YTD' = TOTALYTD([Revenue], Orders[o_orderdate])

	column o_orderkey
		dataType: int64
		isHidden
		sourceColumn: o_orderkey
		summarizeBy: none

	column o_custkey
		dataType: int64
		isHidden
		sourceColumn: o_custkey

	column o_totalprice
		dataType: decimal
		sourceColumn: o_totalprice

	column 'Order Priority'
		dataType: string
		sourceColumn: o_orderpriority

	column o_orderdate
		dataType: dateTime
		sourceColumn: o_orderdate

	column 'Big Order' = IF(Orders[o_totalprice] > 1000, "Yes", "No")
		dataType: string

	partition Orders = m
		mode: import
		source =
				let
				    Source = Databricks.Catalogs("host", "/sql/1.0/warehouses/x", [Catalog=null, Database=null]),
				    cat = Source{[Name="sandbox_source",Kind="Database"]}[Data],
				    sch = cat{[Name="tpch",Kind="Schema"]}[Data],
				    tbl = sch{[Name="orders",Kind="Table"]}[Data]
				in
				    tbl
`;
const CUSTOMER = `table Customer
	column c_custkey
		dataType: int64
		isHidden
		sourceColumn: c_custkey

	column 'Market Segment'
		dataType: string
		sourceColumn: c_mktsegment

	partition Customer = m
		mode: import
		source = \`\`\`
				let
				    Source = Databricks.Catalogs("host", "/sql/1.0/warehouses/x"),
				    cat = Source{[Name="sandbox_source",Kind="Database"]}[Data],
				    sch = cat{[Name="tpch",Kind="Schema"]}[Data],
				    tbl = sch{[Name="customer",Kind="Table"]}[Data]
				in
				    tbl
				\`\`\`
`;
const RELATIONSHIPS = `relationship 0a1b
	fromColumn: Orders.o_custkey
	toColumn: Customer.c_custkey

relationship 2c3d
	isActive: false
	fromColumn: 'Orders'.'o_orderdate'
	toColumn: Customer.c_custkey
`;
const MODEL = `model Model
	culture: en-US

ref table Orders
ref table Customer
`;
const PROJECT = ['\uFEFF' + MODEL, ORDERS, '\uFEFF' + CUSTOMER, RELATIONSHIPS].join('\n');

describe('parseTmdl', () => {
  it('reads tables, measures with multi-line DAX, columns, partitions and relationships', () => {
    const m = parseTmdl(PROJECT.replace(/\uFEFF/g, ''));
    expect(m.tables.map((t) => t.name)).toEqual(['Orders', 'Customer']);
    const orders = m.tables[0];
    expect(orders.description).toBe('Orders of the wholesale business');
    expect(orders.measures.map((x) => [x.name, x.expression])).toEqual([
      ['Revenue', 'SUM(Orders[o_totalprice])'],
      ['Urgent Revenue', 'CALCULATE(\nSUM(Orders[o_totalprice]),\nOrders[Order Priority] = "1-URGENT"\n)'],
      ['Revenue YTD', 'TOTALYTD([Revenue], Orders[o_orderdate])'],
    ]);
    expect(orders.measures[1].description).toBe('Revenue of urgent orders');
    expect(orders.columns.find((c) => c.name === 'o_orderkey')).toMatchObject({ dataType: 'int64', isHidden: true });
    expect(orders.columns.find((c) => c.name === 'Big Order')).toMatchObject({ type: 'calculated' });
    expect(orders.partitions[0].source.expression).toMatch(/Name="orders",Kind="Table"/);
    expect(m.tables[1].partitions[0].source.expression).toMatch(/Name="customer",Kind="Table"/);
    expect(m.relationships).toEqual([
      { fromTable: 'Orders', fromColumn: 'o_custkey', toTable: 'Customer', toColumn: 'c_custkey' },
      { fromTable: 'Orders', fromColumn: 'o_orderdate', toTable: 'Customer', toColumn: 'c_custkey', isActive: false },
    ]);
  });
});

describe('convertTabular with TMDL', () => {
  it('makes the same kind of draft as a .bim file', () => {
    const r = convertTabular('4 files.tmdl', PROJECT, undefined, false);
    expect(r.view?.source).toBe('sandbox_source.tpch.orders');
    expect(r.view?.joins).toEqual([
      { name: 'customer', source: 'sandbox_source.tpch.customer', on: 'source.o_custkey = customer.c_custkey' },
    ]);
    const m = Object.fromEntries(r.view!.measures.map((x) => [x.name, x.expr]));
    expect(m.Revenue).toBe('SUM(o_totalprice)');
    expect(m['Urgent Revenue']).toMatch(/FILTER \(WHERE o_orderpriority = '1-URGENT'\)/);
    expect(r.todo.map((t) => t.name)).toEqual(['Revenue YTD']);
    expect(r.view!.dimensions.map((d) => d.name)).toEqual(['Order Priority', 'O Orderdate', 'Market Segment']);
    expect(validateMetricView(r.preview.yaml!).issues.filter((i) => i.severity === 'error')).toEqual([]);
  });

  it('refuses TMDL files with no table', () => {
    expect(() => convertTabular('model.tmdl', MODEL, undefined, false)).toThrow(/no table/);
  });
});
