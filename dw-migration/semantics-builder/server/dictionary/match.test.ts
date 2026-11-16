import { describe, expect, it } from 'vitest';
import type { DictionaryEntry } from '../../shared/dictionary';
import { validateMetricView } from '../../shared/metricView';
import { certifiedIssues, columnDefinitions, matchEntries } from './match';

const entry = (over: Partial<DictionaryEntry>): DictionaryEntry => ({
  kind: 'metric',
  name: 'X',
  definition: 'd',
  synonyms: [],
  status: 'draft',
  notes: {},
  ...over,
});
const col = (name: string, comment = '') => ({ name, type: 'double', comment });
const lineitem = {
  fullName: 'c.tpch.lineitem',
  comment: '',
  columns: [col('l_extendedprice'), col('l_discount'), col('l_orderkey')],
  primaryKey: [],
  foreignKeys: [],
};
const region = {
  fullName: 'c.tpch.region',
  comment: '',
  columns: [col('r_name', 'Name of the region.')],
  primaryKey: [],
  foreignKeys: [],
};

describe('matchEntries', () => {
  it('matches by source column, then by columns in the formula, and reports the rest', () => {
    const r = matchEntries(
      [
        entry({ name: 'Net Revenue', formula: 'SUM(l_extendedprice * (1 - l_discount))' }),
        entry({ name: 'Customer Region', kind: 'dimension', source: 'samples.tpch.region.r_name' }),
        entry({ name: 'Returns', formula: 'SUM(r_amount)' }),
        entry({ name: 'Order', kind: 'term' }),
      ],
      [lineitem, region]
    );
    expect(r.matched.map((m) => [m.entry.name, m.via, m.columns.map((c) => `${c.table}.${c.column}`)])).toEqual([
      ['Net Revenue', 'formula', ['c.tpch.lineitem.l_extendedprice', 'c.tpch.lineitem.l_discount']],
      ['Customer Region', 'source', ['c.tpch.region.r_name']],
    ]);
    expect(r.unmatched.map((e) => e.name)).toEqual(['Returns']);
    expect(r.terms.map((e) => e.name)).toEqual(['Order']);
  });

  it('supports a derived entry whose formula uses supported entries', () => {
    const r = matchEntries(
      [
        entry({ name: 'Net Revenue', formula: 'SUM(l_extendedprice)' }),
        entry({ name: 'Order Count', formula: 'COUNT(DISTINCT l_orderkey)' }),
        entry({ name: 'Average Order Value', formula: 'Net Revenue / NULLIF(Order Count, 0)' }),
      ],
      [lineitem]
    );
    expect(r.unmatched).toEqual([]);
    expect(r.matched.at(-1)).toMatchObject({ entry: { name: 'Average Order Value' }, via: 'formula' });
    expect(r.matched.at(-1)?.columns.map((c) => c.column)).toEqual(['l_extendedprice', 'l_orderkey']);
  });
});

describe('certifiedIssues', () => {
  const certified = [
    entry({ name: 'Net Revenue', status: 'certified', formula: 'SUM(l_extendedprice * (1 - l_discount))' }),
    entry({ name: 'AOV', status: 'certified', formula: 'Net Revenue / NULLIF(Order Count, 0)' }),
    entry({ name: 'Draft One', status: 'approved', formula: 'SUM(x)' }),
  ];
  const view = (measures: string) =>
    validateMetricView(`version: 1.1\nsource: c.tpch.lineitem\nmeasures:\n${measures}`).view!;

  it('accepts the certified formula with qualifiers and MEASURE()', () => {
    expect(
      certifiedIssues(
        view(`  - name: Net Revenue
    expr: SUM(source.l_extendedprice * (1 - source.l_discount))
  - name: Order Count
    expr: COUNT(DISTINCT l_orderkey)
  - name: AOV
    expr: MEASURE(\`Net Revenue\`) / NULLIF(MEASURE(\`Order Count\`), 0)
`),
        certified
      )
    ).toEqual([]);
  });

  it('blocks a changed formula and a renamed certified measure', () => {
    const issues = certifiedIssues(
      view(`  - name: net_revenue
    expr: SUM(l_extendedprice)
`),
      certified
    );
    expect(issues.map((i) => i.severity)).toEqual(['error', 'error']);
    expect(issues[0].message).toMatch(/certified name exactly: "Net Revenue"/);
    expect(issues[1].message).toMatch(/certified formula/);
  });
});

describe('columnDefinitions', () => {
  it('keeps one-column dimension matches, not metrics or formulas', () => {
    const defs = columnDefinitions(
      [
        entry({
          name: 'Customer Region',
          kind: 'dimension',
          definition: 'Region of the customer.',
          source: 'x.tpch.region.r_name',
        }),
        entry({ name: 'Net Revenue', definition: 'After discounts.', formula: 'SUM(l_extendedprice)' }),
        entry({ name: 'Gross', definition: 'Before discounts.', source: 'x.tpch.lineitem.l_extendedprice' }),
      ],
      [lineitem, region]
    );
    expect([...defs.keys()]).toEqual(['c.tpch.region']);
    expect(defs.get('c.tpch.region')?.get('r_name')).toEqual({
      text: 'Region of the customer.',
      entry: 'Customer Region',
    });
  });
});
