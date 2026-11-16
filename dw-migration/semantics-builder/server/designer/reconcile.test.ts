import { describe, expect, it } from 'vitest';
import { autoMap, parseCsv, parseNumber, reconcileBody, reconcileTests } from '../../shared/reconcile';
import { compareReconcile, reconcileQuery } from './reconcile';

describe('parseCsv and parseNumber', () => {
  it('reads quotes and the delimiter of the header line', () => {
    expect(parseCsv('Region,"Net, Revenue"\nASIA,"1,234.50"\n\n"EU ""west""",2\n')).toEqual({
      header: ['Region', 'Net, Revenue'],
      rows: [
        ['ASIA', '1,234.50'],
        ['EU "west"', '2'],
      ],
      delimiter: ',',
    });
    expect(parseCsv('Region;Revenue\r\nASIA;1.234,5').rows).toEqual([['ASIA', '1.234,5']]);
    expect(parseCsv('a\tb\n1\t2').delimiter).toBe('\t');
  });

  it('reads report numbers', () => {
    expect(parseNumber('1,234.50')).toBe(1234.5);
    expect(parseNumber('1.234,50')).toBe(1234.5);
    expect(parseNumber('1,5')).toBe(1.5);
    expect(parseNumber('1.234', ';')).toBe(1234);
    expect(parseNumber('$ (1,200)')).toBe(-1200);
    expect(parseNumber('-3.5')).toBe(-3.5);
    expect(parseNumber('12%')).toBeCloseTo(0.12);
    expect(parseNumber('')).toBeNull();
    expect(Number.isNaN(parseNumber('n/a'))).toBe(true);
  });

  it('maps columns to fields by name', () => {
    expect(autoMap(['region', 'Net_Revenue', 'Notes'], { dimensions: ['Region'], measures: ['Net Revenue'] })).toEqual([
      { kind: 'dimension', name: 'Region' },
      { kind: 'measure', name: 'Net Revenue' },
      null,
    ]);
  });
});

describe('reconcile', () => {
  const body = reconcileBody.parse({
    dimensions: ['Region', 'Order Month'],
    measures: ['Net Revenue', 'Orders'],
    rows: [
      { keys: ['ASIA', '1995-01-01'], values: [100, 10] },
      { keys: ['EUROPE', '1995-01-01'], values: [200, null] },
      { keys: ['AFRICA', '1995-01-01'], values: [50, 5] },
      { keys: ['ASIA', '1995-02-01'], values: [0, 3] },
    ],
    tolerancePct: 1,
  });

  it('filters the view to the keys of the report', () => {
    expect(reconcileQuery('s.v.mv', body)).toBe(
      "SELECT CAST(`Region` AS STRING) AS `Region`, CAST(`Order Month` AS STRING) AS `Order Month`, MEASURE(`Net Revenue`) AS `Net Revenue`, MEASURE(`Orders`) AS `Orders` FROM `s`.`v`.`mv` WHERE CAST(`Region` AS STRING) IN ('ASIA', 'EUROPE', 'AFRICA') AND CAST(`Order Month` AS STRING) IN ('1995-01-01', '1995-01-01 00:00:00', '1995-02-01', '1995-02-01 00:00:00') GROUP BY ALL LIMIT 20001"
    );
    const years = reconcileBody.parse({ ...body, dimensions: ['Year'], rows: [{ keys: ['1995'], values: [1, 2] }] });
    expect(reconcileQuery('s.v.mv', years)).toContain('WHERE `Year` IN (1995)');
    const total = reconcileBody.parse({
      dimensions: [],
      measures: ['Orders'],
      rows: [{ keys: [], values: [5] }],
      tolerancePct: 0,
    });
    expect(reconcileQuery('s.v.mv', total)).toBe('SELECT MEASURE(`Orders`) AS `Orders` FROM `s`.`v`.`mv` LIMIT 20001');
  });

  it('compares each cell with the tolerance, and finds missing rows', () => {
    const r = compareReconcile(body, [
      ['ASIA', '1995-01-01 00:00:00', '100.5', '10'],
      ['EUROPE', '1995-01-01 00:00:00', '210', '7'],
      ['ASIA', '1995-02-01 00:00:00', '0', '4'],
    ]);
    expect(r.rows.map((x) => x.cells.map((c) => c.status))).toEqual([
      ['passed', 'passed'],
      ['failed', 'skipped'],
      ['missing', 'missing'],
      ['passed', 'failed'],
    ]);
    expect(r.rows[1].cells[0].diffPct).toBe(5);
    expect(r.counts).toEqual({ passed: 3, failed: 2, missing: 2, skipped: 1 });
    expect(r.truncated).toBe(false);

    const tests = reconcileTests({ sandboxView: 'x', sql: '', ...r }, body.dimensions, 1, []);
    expect(tests.map((t) => t.name)).toEqual([
      'Reconcile Net Revenue (Region = ASIA, Order Month = 1995-01-01)',
      'Reconcile Orders (Region = ASIA, Order Month = 1995-01-01)',
      'Reconcile Net Revenue (Region = ASIA, Order Month = 1995-02-01)',
    ]);
    expect(tests[0].expect).toEqual({
      value: 100,
      tolerancePct: 1,
      filters: [
        { dimension: 'Region', value: 'ASIA' },
        { dimension: 'Order Month', value: '1995-01-01' },
      ],
    });
    expect(reconcileTests({ sandboxView: 'x', sql: '', ...r }, body.dimensions, 1, [], 2)).toHaveLength(2);
  });

  it('refuses rows that do not fit the columns', () => {
    expect(
      reconcileBody.safeParse({
        dimensions: ['A'],
        measures: ['M'],
        rows: [{ keys: [], values: [1] }],
        tolerancePct: 1,
      }).success
    ).toBe(false);
    expect(
      reconcileBody.safeParse({
        dimensions: [],
        measures: ['M'],
        rows: [
          { keys: [], values: [1] },
          { keys: [], values: [2] },
        ],
        tolerancePct: 1,
      }).success
    ).toBe(false);
  });
});
