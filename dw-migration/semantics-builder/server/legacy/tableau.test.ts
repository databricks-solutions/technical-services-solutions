import { describe, expect, it } from 'vitest';
import { validateMetricView } from '../../shared/metricView';
import { convertTableau } from './tableau';
import { translateTableau } from './tableauCalc';
import { parseXml } from './xml';
import { zipOf } from './zip.fixture';

const record = (table: string, remote: string, type: string, agg = 'Sum') =>
  `<metadata-record class='column'><remote-name>${remote}</remote-name><remote-type>0</remote-type><local-name>[${remote}]</local-name><parent-name>[${table}]</parent-name><local-type>${type}</local-type><aggregation>${agg}</aggregation></metadata-record>`;

const TWB = `<?xml version='1.0' encoding='utf-8' ?>
<workbook version='18.1'>
  <datasources>
    <datasource name='Parameters' hasconnection='false' />
    <datasource caption='Orders' name='federated.1'>
      <connection class='federated'>
        <named-connections>
          <named-connection caption='dbx' name='databricks.1'>
            <connection class='databricks' dbname='sandbox_source' schema='tpch' server='adb.example.net' />
          </named-connection>
        </named-connections>
        <relation join='inner' type='join'>
          <clause type='join'>
            <expression op='='><expression op='[orders].[o_custkey]' /><expression op='[customer].[c_custkey]' /></expression>
          </clause>
          <relation connection='databricks.1' name='orders' table='[tpch].[orders]' type='table' />
          <relation connection='databricks.1' name='customer' table='[tpch].[customer]' type='table' />
        </relation>
        <metadata-records>
          ${record('orders', 'o_orderkey', 'integer')}
          ${record('orders', 'o_custkey', 'integer')}
          ${record('orders', 'o_orderpriority', 'string', 'Count')}
          ${record('orders', 'o_orderdate', 'date', 'Year')}
          ${record('orders', 'o_totalprice', 'real')}
          ${record('customer', 'c_custkey', 'integer')}
          ${record('customer', 'c_mktsegment', 'string', 'Count')}
          ${record('customer', 'c_acctbal', 'real', 'Avg')}
        </metadata-records>
      </connection>
      <column caption='Order Priority' datatype='string' name='[o_orderpriority]' role='dimension' type='nominal' />
      <column caption='Total Price' datatype='real' name='[o_totalprice]' role='measure' type='quantitative' />
      <column caption='Account Balance' datatype='real' name='[c_acctbal]' role='measure' type='quantitative' hidden='true' />
      <column caption='Urgent Price' datatype='real' name='[Calculation_1]' role='measure' type='quantitative'>
        <calculation class='tableau' formula='SUM(IF [Order Priority] = &apos;1-URGENT&apos; THEN [o_totalprice] END)' />
      </column>
      <column caption='Average Price' datatype='real' name='[Calculation_2]' role='measure' type='quantitative'>
        <calculation class='tableau' formula='[Total Price Sum] / COUNTD([o_orderkey])' />
      </column>
      <column caption='Total Price Sum' datatype='real' name='[Calculation_3]' role='measure' type='quantitative'>
        <calculation class='tableau' formula='SUM([o_totalprice])' />
      </column>
      <column caption='Order Month' datatype='date' name='[Calculation_4]' role='dimension' type='ordinal'>
        <calculation class='tableau' formula='DATETRUNC(&apos;month&apos;, [o_orderdate])' />
      </column>
      <column caption='Fixed Total' datatype='real' name='[Calculation_5]' role='measure' type='quantitative'>
        <calculation class='tableau' formula='{FIXED [c_mktsegment] : SUM([o_totalprice])}' />
      </column>
    </datasource>
  </datasources>
</workbook>`;

describe('parseXml', () => {
  it('reads elements and entities, and refuses DOCTYPE and entity declarations', () => {
    const n = parseXml(`<a x='1 &amp; 2'><b>t&lt;</b><c/></a>`).children[0];
    expect(n.attrs.x).toBe('1 & 2');
    expect(n.children.map((c) => [c.tag, c.text])).toEqual([
      ['b', 't<'],
      ['c', ''],
    ]);
    expect(() => parseXml('<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><a>&e;</a>')).toThrow(/DOCTYPE/);
    expect(() => parseXml('<a><b></a>')).toThrow(/does not match/);
  });
});

describe('translateTableau', () => {
  const t = (f: string) => translateTableau(f, { field: (n) => ({ Sales: 'sales', Region: 'region' })[n] ?? null });
  it('translates calculations, and returns null for LOD and table calculations', () => {
    expect(t('ZN(SUM([Sales]))')).toBe('COALESCE(SUM(sales), 0)');
    expect(t("IIF([Region] == 'East', 1, 0)")).toBe("CASE WHEN region = 'East' THEN 1 ELSE 0 END");
    expect(t("IF [Region] = 'A' THEN 1 ELSEIF [Region] = 'B' THEN 2 ELSE 3 END")).toBe(
      "CASE WHEN region = 'A' THEN 1 WHEN region = 'B' THEN 2 ELSE 3 END"
    );
    expect(t('{FIXED [Region] : SUM([Sales])}')).toBeNull();
    expect(t('RUNNING_SUM(SUM([Sales]))')).toBeNull();
    expect(t('SUM([Profit])')).toBeNull();
  });
});

describe('convertTableau', () => {
  const r = convertTableau('orders.twb', TWB, undefined, false);
  const expr = Object.fromEntries([...r.view!.dimensions, ...r.view!.measures].map((f) => [f.name, f.expr]));
  const status = Object.fromEntries(r.preview.fields.map((f) => [f.name, f.status]));

  it('makes a valid metric view from the data source, its join and its connection', () => {
    expect(r.preview.sources).toEqual(['sandbox_source.tpch.orders', 'sandbox_source.tpch.customer']);
    expect(r.view!.joins).toEqual([
      { name: 'customer', source: 'sandbox_source.tpch.customer', on: 'source.o_custkey = customer.c_custkey' },
    ]);
    expect(r.preview.issues).toEqual([]);
    expect(validateMetricView(r.preview.yaml!).issues.filter((i) => i.severity === 'error')).toEqual([]);
  });

  it('converts columns and calculations, and sends the rest to the AI', () => {
    expect(expr['Order Priority']).toBe('o_orderpriority');
    expect(expr['Total Price']).toBe('SUM(o_totalprice)');
    expect(expr['C Mktsegment']).toBe('customer.c_mktsegment');
    expect(expr['Urgent Price']).toBe("SUM(CASE WHEN o_orderpriority = '1-URGENT' THEN o_totalprice END)");
    expect(expr['Average Price']).toBe('MEASURE(`Total Price Sum`) / COUNT(DISTINCT o_orderkey)');
    expect(expr['Order Month']).toBe("DATE_TRUNC('MONTH', o_orderdate)");
    expect(Object.keys(expr)).not.toContain('Account Balance');
    expect(Object.keys(expr)).not.toContain('O Orderkey');
    expect(status['Fixed Total']).toBe('manual');
    expect(r.todo.map((x) => x.name)).toEqual(['Fixed Total']);
    const ai = convertTableau('orders.twb', TWB, undefined, false, new Map([['Fixed Total', 'SUM(o_totalprice)']]));
    expect(ai.preview.fields.find((f) => f.name === 'Fixed Total')?.status).toBe('review');
  });

  it('reads the object model relationships, and the .twb in a .twbx', () => {
    const om = TWB.replace(/<clause type='join'>[\s\S]*?<\/clause>/, '').replace(
      '</metadata-records>',
      `</metadata-records><object-graph><relationships><relationship><expression op='='><expression op='[o_custkey]' /><expression op='[c_custkey]' /></expression></relationship></relationships></object-graph>`
    );
    expect(convertTableau('om.twb', om, undefined, false).view!.joins?.[0].on).toBe(
      'source.o_custkey = customer.c_custkey'
    );
    const twbx = zipOf('orders.twb', Buffer.from(TWB)).toString('base64');
    expect(convertTableau('orders.twbx', twbx, undefined, true).preview.yaml).toBe(r.preview.yaml);
  });
});
