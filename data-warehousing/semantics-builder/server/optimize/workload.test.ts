import { describe, expect, it } from 'vitest';
import { validateMetricView } from '../../shared/metricView';
import { buildWorkload, stressSql, summarize } from './workload';

const view = validateMetricView(`version: 1.1
source: c.s.orders
dimensions:
  - name: Order Month
    expr: DATE_TRUNC('MONTH', o_orderdate)
  - name: Region
    expr: r_name
measures:
  - name: Revenue
    expr: SUM(o_totalprice)
  - name: Revenue PY
    expr: MEASURE(Revenue)
    window:
      - order: Order Month
        range: current
        offset: -12 month
  - name: Growth
    expr: (MEASURE(Revenue) - MEASURE(\`Revenue PY\`)) / MEASURE(\`Revenue PY\`)
`).view!;

describe('buildWorkload', () => {
  it('starts with the tests, then one query per dimension', () => {
    const w = buildWorkload(view, [{ name: 'By region', dimensions: ['Region'], measures: ['Revenue'] }]);
    expect(w[0]).toMatchObject({ label: 'By region', origin: 'test' });
    expect(w.map((q) => q.dimensions)).toEqual([['Region'], ['Order Month']]);
  });

  it('adds window measures, and measures built on them, only with their order dimension', () => {
    const [month] = buildWorkload(view, []).filter((q) => q.dimensions.includes('Order Month'));
    expect(month.measures).toEqual(['Revenue', 'Revenue PY', 'Growth']);
    const [region] = buildWorkload(view, []).filter((q) => q.dimensions.includes('Region'));
    expect(region.measures).toEqual(['Revenue']);
  });

  it('drops duplicates of a test', () => {
    const w = buildWorkload(view, [{ name: 't', dimensions: ['Region'], measures: ['Revenue'] }]);
    expect(w).toHaveLength(2);
  });
});

describe('stressSql', () => {
  it('quotes names and adds a unique literal column that bypasses the result cache', () => {
    expect(stressSql('c.s.v', { dimensions: ['Order Month'], measures: ['Revenue'] }, 17)).toBe(
      "SELECT `Order Month`, MEASURE(`Revenue`) AS `Revenue`, 'gsb-17' AS gsb_run FROM `c`.`s`.`v` GROUP BY ALL LIMIT 1001"
    );
  });
});

describe('summarize', () => {
  it('reports cold, warm median and max, and flags slow and spilling queries', () => {
    const s = summarize(
      [
        { wallMs: 9000, execMs: 8000, readBytes: 10, rowsRead: 5 },
        { wallMs: 6000, execMs: 6000, spillBytes: 1 },
        { wallMs: 7000, execMs: 7000 },
      ],
      5000
    );
    expect(s).toMatchObject({ coldMs: 8000, warmMs: 6500, maxMs: 8000, readBytes: 10, rowsRead: 5 });
    expect(s.flags).toEqual(['slow', 'spill']);
  });

  it('leaves cached runs out of the times', () => {
    const s = summarize(
      [
        { wallMs: 3000, execMs: 3000 },
        { wallMs: 40, execMs: 40, fromCache: true },
        { wallMs: 2000, execMs: 2000 },
      ],
      5000
    );
    expect(s).toMatchObject({ coldMs: 3000, warmMs: 2000, maxMs: 3000 });
  });

  it('flags errors and full scans of large data', () => {
    expect(summarize([{ wallMs: 1, error: 'boom' }], 5000).flags).toEqual(['error']);
    expect(summarize([{ wallMs: 1, execMs: 1, readBytes: 2 ** 31, prunedBytes: 0 }], 5000).flags).toEqual([
      'no_pruning',
    ]);
  });
});
