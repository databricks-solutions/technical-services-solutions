import { describe, expect, it } from 'vitest';
import { renderMetricView, validateMetricView } from './metricView';
import { addTimeIntelligence, grainOf } from './timeIntelligence';

const view = validateMetricView(`version: 1.1
source: samples.tpch.orders
fields:
  - name: Order Month
    expr: DATE_TRUNC('MONTH', source.o_orderdate)
measures:
  - name: Revenue
    expr: SUM(source.o_totalprice)
    format:
      type: currency
      currency_code: USD
`).view!;

describe('grainOf', () => {
  it('reads DATE_TRUNC, YEAR and date columns', () => {
    expect(grainOf("DATE_TRUNC('QUARTER', d)")).toBe('quarter');
    expect(grainOf('YEAR(o_orderdate)')).toBe('year');
    expect(grainOf('o_orderdate')).toBe('day');
    expect(grainOf('o_orderstatus')).toBeNull();
  });
});

describe('addTimeIntelligence', () => {
  const all = addTimeIntelligence(view, {
    measure: 'Revenue',
    dimension: 'Order Month',
    grain: 'month',
    kinds: ['to_date', 'previous', 'last_year', 'growth', 'rolling'],
  });

  it('adds the year dimension and the window measures, and the YAML is valid', () => {
    expect(all.added).toEqual([
      'Order Month Year',
      'Revenue YTD',
      'Revenue PP',
      'Revenue PY',
      'Revenue PoP %',
      'Revenue YoY %',
      'Revenue 3M',
    ]);
    const out = validateMetricView(renderMetricView(all.view));
    expect(out.issues.filter((i) => i.severity === 'error')).toEqual([]);
    const m = (n: string) => out.view!.measures.find((x) => x.name === n)!;
    expect(m('Revenue PY').window).toEqual([{ order: 'Order Month', range: 'current', offset: '-12 month' }]);
    expect(m('Revenue 3M').window).toEqual([{ order: 'Order Month', range: 'trailing 3 month inclusive' }]);
    expect(out.view!.dimensions.find((d) => d.name === 'Order Month Year')!.expr).toBe('YEAR(source.o_orderdate)');
    // Unity Catalog does not read YAML anchors, and the measures share format objects.
    expect(renderMetricView(all.view)).not.toMatch(/[&*]a\d/);
  });

  it('writes weeks as days and quarters as months, which are the periods that Unity Catalog accepts', () => {
    const q = validateMetricView(`version: 1.1
source: c.s.t
fields:
  - name: Week
    expr: DATE_TRUNC('WEEK', d)
  - name: Quarter
    expr: DATE_TRUNC('QUARTER', d)
measures:
  - name: Orders
    expr: COUNT(1)
`).view!;
    const w = (dimension: string, grain: 'week' | 'quarter') =>
      addTimeIntelligence(q, { measure: 'Orders', dimension, grain, kinds: ['last_year', 'rolling'] }).view.measures.flatMap(
        (m) => m.window ?? []
      );
    expect(w('Week', 'week')).toEqual([
      { order: 'Week', range: 'current', offset: '-364 day' },
      { order: 'Week', range: 'trailing 21 day inclusive' },
    ]);
    expect(w('Quarter', 'quarter')).toEqual([
      { order: 'Quarter', range: 'current', offset: '-12 month' },
      { order: 'Quarter', range: 'trailing 9 month inclusive' },
    ]);
  });

  it('adds nothing the second time', () => {
    expect(
      addTimeIntelligence(all.view, {
        measure: 'Revenue',
        dimension: 'Order Month',
        grain: 'month',
        kinds: ['to_date', 'growth'],
      }).added
    ).toEqual([]);
  });
});
