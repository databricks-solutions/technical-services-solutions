import { describe, expect, it } from 'vitest';
import { renderMetricView, validateMetricView } from '../../shared/metricView';
import type { DesignOutput } from '../llm/prompts/designer';
import type { TableProfile } from '../readiness/profile';
import { buildDesign, toSourceProfiles } from './build';

const table = (fullName: string, columns: string[], primaryKey: string[]): TableProfile => ({
  fullName,
  comment: '',
  columns: columns.map((name) => ({ name, type: 'string', comment: '' })),
  primaryKey,
  foreignKeys: [],
});

const profiles = [
  table('s.t.lineitem', ['l_orderkey', 'l_extendedprice', 'l_discount'], []),
  table('s.t.orders', ['o_orderkey', 'o_custkey', 'o_orderdate'], ['o_orderkey']),
  table('s.t.customer', ['c_custkey', 'c_mktsegment'], ['c_custkey']),
];

const field = (name: string, expr: string) => ({
  name,
  expr,
  comment: `${name}.`,
  displayName: null,
  synonyms: [],
  format: null,
  explanation: `How ${name} works.`,
});

const output: DesignOutput = {
  name: 'sales_metrics',
  comment: 'Sales.',
  source: 'S.T.LINEITEM',
  filter: null,
  joins: [
    {
      name: 'dim_orders',
      source: 's.t.orders',
      parent: null,
      keys: [{ parentColumn: 'l_orderkey', column: 'o_orderkey' }],
    },
    {
      name: 'customer',
      source: 's.t.customer',
      parent: 'dim_orders',
      keys: [{ parentColumn: 'o_custkey', column: 'c_custkey' }],
    },
  ],
  dimensions: [
    field('Order Month', "DATE_TRUNC('MONTH', dim_orders.o_orderdate)"),
    field('Segment', 'dim_orders.customer.c_mktsegment'),
  ],
  measures: [
    { ...field('Net Revenue', 'SUM(source.l_extendedprice * (1 - source.l_discount))'), additivity: 'additive' },
    { ...field('Orders', 'COUNT(DISTINCT source.l_orderkey)'), additivity: 'non_additive' },
  ],
  tests: [
    { name: 'By month', dimensions: ['Order Month'], measures: ['Net Revenue'] },
    { name: 'By segment', dimensions: ['Segment'], measures: ['Orders', 'Net Revenue'] },
    { name: 'Bad', dimensions: ['Nation'], measures: ['Net Revenue'] },
  ],
  summary: 'Net revenue by month and segment.',
};

describe('buildDesign', () => {
  it('builds a snowflake view that validates against the profiles', () => {
    const design = buildDesign(
      output,
      profiles.map((p) => p.fullName)
    );
    expect(design.view.source).toBe('s.t.lineitem');
    expect(design.view.joins?.[0]).toMatchObject({
      on: 'source.l_orderkey = dim_orders.o_orderkey',
      joins: [{ name: 'customer', on: 'dim_orders.o_custkey = customer.c_custkey' }],
    });
    expect(validateMetricView(renderMetricView(design.view), toSourceProfiles(profiles)).issues).toEqual([]);
    expect(design.tests.map((t) => t.name)).toEqual(['By month', 'By segment']);
    expect(design.explanations.measures['Orders']).toEqual({
      additivity: 'non_additive',
      explanation: 'How Orders works.',
    });
  });

  it('quotes unusual key columns and rejects unknown tables or parents', () => {
    const odd = {
      ...output,
      joins: [{ ...output.joins[0], keys: [{ parentColumn: 'order key', column: 'o_orderkey' }] }],
    };
    expect(buildDesign(odd, ['s.t.lineitem', 's.t.orders']).view.joins?.[0]?.on).toBe(
      'source.`order key` = dim_orders.o_orderkey'
    );
    expect(() => buildDesign({ ...output, source: 's.t.other' }, ['s.t.lineitem'])).toThrow(/not a project table/);
    expect(() =>
      buildDesign(
        { ...output, joins: [output.joins[1]] },
        profiles.map((p) => p.fullName)
      )
    ).toThrow(/before its parent/);
  });

  it('renders window measures that the validator accepts', () => {
    const windowed: DesignOutput = {
      ...output,
      measures: [
        ...output.measures,
        {
          ...field('Net Revenue PM', 'MEASURE(`Net Revenue`)'),
          additivity: 'additive',
          window: [{ order: 'Order Month', range: 'current', semiadditive: null, offset: '-1 month' }],
        },
        {
          ...field('Net Revenue YTD', 'MEASURE(`Net Revenue`)'),
          additivity: 'additive',
          window: [{ order: 'Order Month', range: 'cumulative', semiadditive: null, offset: null }],
        },
      ],
    };
    const { view } = buildDesign(
      windowed,
      profiles.map((p) => p.fullName)
    );
    const yaml = renderMetricView(view);
    expect(yaml).toContain('offset: -1 month');
    expect(yaml).not.toMatch(/semiadditive|offset: null/);
    expect(validateMetricView(yaml, toSourceProfiles(profiles)).issues.filter((i) => i.severity === 'error')).toEqual(
      []
    );
    const bad = {
      ...windowed.measures[2],
      window: [{ order: 'Nope', range: 'current', semiadditive: null, offset: null }],
    };
    const badYaml = renderMetricView(
      buildDesign(
        { ...windowed, measures: [...output.measures, bad] },
        profiles.map((p) => p.fullName)
      ).view
    );
    expect(validateMetricView(badYaml).issues[0]?.message).toMatch(/Window order "Nope" is not a dimension/);
  });
});
