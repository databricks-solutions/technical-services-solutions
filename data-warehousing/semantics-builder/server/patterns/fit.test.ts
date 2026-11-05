import { beforeAll, describe, expect, it } from 'vitest';
import type { Pattern } from '../../shared/patterns';
import { join } from 'node:path';
import { loadPatterns } from './library';
import { hasRule, patternFit } from './fit';
import type { TableProfile } from '../readiness/profile';

const t = (fullName: string, cols: [string, string][]): TableProfile => ({
  fullName,
  comment: '',
  columns: cols.map(([name, type]) => ({ name, type, comment: '' })),
  primaryKey: [],
  foreignKeys: [],
});

const tpch = [
  t('c.tpch.lineitem', [
    ['l_orderkey', 'bigint'],
    ['l_extendedprice', 'decimal(18,2)'],
    ['l_discount', 'decimal(18,2)'],
    ['l_shipdate', 'date'],
    ['l_receiptdate', 'date'],
  ]),
  t('c.tpch.orders', [
    ['o_orderkey', 'bigint'],
    ['o_custkey', 'bigint'],
    ['o_totalprice', 'decimal(18,2)'],
    ['o_orderdate', 'date'],
  ]),
  t('c.tpch.customer', [
    ['c_custkey', 'bigint'],
    ['c_mktsegment', 'string'],
    ['c_acctbal', 'decimal(18,2)'],
  ]),
];

let patterns: Pattern[] = [];
beforeAll(async () => {
  patterns = (await loadPatterns(join(__dirname, '../../patterns'))).patterns;
});
const bySlug = (s: string) => patterns.find((p) => p.slug === s)!;

describe('patternFit', () => {
  it('has a rule for every role in the library', () => {
    expect(patterns.length).toBeGreaterThan(0);
    expect(patterns.flatMap((p) => p.roles.map((r) => r.name)).filter((r) => !hasRule(r))).toEqual([]);
  });

  it('fits period over period on TPC-H orders', () => {
    const fit = patternFit(bySlug('period_over_period'), tpch);
    expect(fit.status).toBe('fits');
    expect(fit.found.map((f) => f.match)).toContain('orders.o_orderdate');
  });

  it('reports the missing snapshot date for semi-additive balances', () => {
    const fit = patternFit(bySlug('semi_additive'), tpch);
    expect(fit.status).toBe('partial');
    expect(fit.missing).toContain('snapshot_date');
  });

  it('finds role-playing dates on a fact with several dates', () => {
    expect(patternFit(bySlug('role_playing_dimensions'), tpch).status).toBe('fits');
  });

  it('uses different columns for the two sides of a ratio', () => {
    const f = patternFit(bySlug('ratio_measures'), tpch).found;
    expect(new Set(f.map((x) => x.match)).size).toBe(f.length);
  });
});
