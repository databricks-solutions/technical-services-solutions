import { describe, expect, it } from 'vitest';
import { validateMetricView } from '../../shared/metricView';
import type { StressQueryResult } from '../../shared/optimize';
import { isAdditive, matchedName, suggestMaterializations, withMaterialization } from './materialize';

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
  - name: Customers
    expr: COUNT(DISTINCT o_custkey)
  - name: AOV
    expr: MEASURE(Revenue) / MEASURE(Customers)
`).view!;

const q = (label: string, dimensions: string[], measures: string[], warmMs: number | null): StressQueryResult => ({
  label,
  dimensions,
  measures,
  origin: 'generated',
  sql: '',
  attempts: [],
  coldMs: warmMs,
  warmMs,
  maxMs: warmMs,
  readBytes: null,
  rowsRead: null,
  flags: [],
});

describe('isAdditive', () => {
  it('accepts SUM, COUNT, MIN and MAX, not distinct counts or ratios', () => {
    const m = new Map(view.measures.map((x) => [x.name, x]));
    expect(isAdditive(m.get('Revenue')!)).toBe(true);
    expect(isAdditive(m.get('Customers')!)).toBe(false);
    expect(isAdditive(m.get('AOV')!)).toBe(false);
  });
});

describe('suggestMaterializations', () => {
  it('suggests one aggregated view per dimension set, slowest first, and skips fast queries', () => {
    const s = suggestMaterializations(view, 'run1', [
      q('By month', ['Order Month'], ['Revenue', 'AOV'], 3000),
      q('By month and region', ['Order Month', 'Region'], ['Customers'], 4000),
      q('Fast', ['Region'], ['Customers'], 200),
      q('Broken', ['Region'], ['Revenue'], null),
    ]);
    expect(s.views.map((v) => [v.name, v.dimensions, v.measures])).toEqual([
      ['mv_order_month_region', ['Order Month', 'Region'], ['Customers']],
      ['mv_order_month', ['Order Month'], ['Revenue', 'AOV']],
    ]);
    expect(s.skipped.map((x) => x.label)).toEqual(['Fast', 'Broken']);
  });

  it('serves a query with only additive measures by rollup from a wider view', () => {
    const s = suggestMaterializations(view, 'run1', [
      q('Wide', ['Order Month', 'Region'], ['Revenue'], 4000),
      q('Narrow', ['Region'], ['Revenue'], 3000),
    ]);
    expect(s.views.map((v) => v.name)).toEqual(['mv_order_month_region']);
    expect(s.views[0].queries).toEqual(['Wide', 'Narrow']);
  });
});

describe('withMaterialization', () => {
  it('adds the block to the YAML', () => {
    const yaml = withMaterialization(view, 'every 24 hours', [
      { name: 'mv_r', type: 'aggregated', dimensions: ['Region'], measures: ['Revenue'], queries: [], reason: '' },
    ]);
    const back = validateMetricView(yaml);
    expect(back.issues.filter((i) => i.severity === 'error')).toEqual([]);
    expect(yaml).toContain('materialization:');
    expect(yaml).toContain('schedule: every 24 hours');
    expect(yaml).toContain('mode: relaxed');
  });
});

describe('matchedName', () => {
  it('finds the materialization a plan reads', () => {
    const plan = 'Relation __materialization_mat_6d14___metric_view_mat_5420 mv_order_month_region_7cb6';
    expect(matchedName(plan, ['mv_order_month', 'mv_order_month_region'])).toBe('mv_order_month_region');
    expect(matchedName('__materialization_mat_1 mv_order_month_9f', ['mv_order_month', 'mv_order_month_region'])).toBe(
      'mv_order_month'
    );
    expect(matchedName('Relation samples.tpch.orders', ['mv_order_month'])).toBeNull();
  });
});
