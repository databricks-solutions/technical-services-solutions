import { describe, expect, it } from 'vitest';
import { applyEffect, inferLinks, projectScore, tableAreas } from './score';
import type { TableProfile } from './profile';

const t = (fullName: string, cols: [string, string][], extra: Partial<TableProfile> = {}): TableProfile => ({
  fullName,
  comment: '',
  columns: cols.map(([name, type]) => ({ name, type, comment: '' })),
  primaryKey: [],
  foreignKeys: [],
  ...extra,
});

const lineitem = t('c.s.lineitem', [
  ['l_orderkey', 'bigint'],
  ['l_partkey', 'bigint'],
  ['l_extendedprice', 'decimal(18,2)'],
  ['l_shipdate', 'string'],
]);
const orders = t('c.s.orders', [
  ['o_orderkey', 'bigint'],
  ['o_custkey', 'bigint'],
  ['o_orderdate', 'date'],
]);
const customer = t('c.s.customer', [
  ['c_custkey', 'bigint'],
  ['c_nationkey', 'bigint'],
]);
const part = t('c.s.part', [['p_partkey', 'bigint']]);
const partsupp = t('c.s.partsupp', [
  ['ps_partkey', 'bigint'],
  ['ps_suppkey', 'bigint'],
]);
const users = t('c.s.users', [['id', 'bigint']]);
const events = t('c.s.events', [['user_id', 'bigint']]);

describe('inferLinks', () => {
  it('matches TPC-H style key names to the owning table', () => {
    const links = inferLinks([lineitem, orders, customer, part, partsupp]);
    expect(links).toContainEqual({
      from: 'c.s.lineitem',
      column: 'l_orderkey',
      to: 'c.s.orders',
      refColumn: 'o_orderkey',
    });
    expect(links).toContainEqual({
      from: 'c.s.orders',
      column: 'o_custkey',
      to: 'c.s.customer',
      refColumn: 'c_custkey',
    });
    // part is a closer name match than partsupp.
    expect(links).toContainEqual({ from: 'c.s.lineitem', column: 'l_partkey', to: 'c.s.part', refColumn: 'p_partkey' });
    expect(links.some((l) => l.column === 'o_orderkey')).toBe(false);
  });

  it('matches name_id to a table with an id column', () => {
    expect(inferLinks([events, users])).toEqual([
      { from: 'c.s.events', column: 'user_id', to: 'c.s.users', refColumn: 'id' },
    ]);
  });
});

describe('tableAreas', () => {
  it('scores documentation, keys, types and naming', () => {
    const areas = tableAreas(lineitem, [lineitem, orders]);
    const by = Object.fromEntries(areas.map((a) => [a.id, a.score]));
    expect(by.documentation).toBe(0);
    expect(by.keys).toBe(0);
    // l_shipdate is text, l_extendedprice is numeric.
    expect(by.types).toBe(50);
    expect(by.naming).toBe(0);
  });

  it('gives full key credit for a declared key and declared link', () => {
    const linked = {
      ...lineitem,
      primaryKey: ['l_orderkey', 'l_partkey'],
      foreignKeys: [{ columns: ['l_orderkey'], references: 'c.s.orders', refColumns: ['o_orderkey'] }],
    };
    expect(tableAreas(linked, [linked, orders]).find((a) => a.id === 'keys')?.score).toBe(100);
  });
});

describe('projectScore', () => {
  it('weights the areas and includes brief coverage', () => {
    const doc = { ...customer, comment: 'Customers', columns: customer.columns.map((c) => ({ ...c, comment: 'x' })) };
    const s = projectScore([doc], { covered: 1, total: 2, missing: ['Region'] });
    expect(s.areas.find((a) => a.id === 'coverage')?.score).toBe(50);
    expect(s.score).toBeGreaterThan(0);
    expect(s.score).toBeLessThanOrEqual(100);
  });

  it('raises the score when a fix is applied', () => {
    const before = projectScore([orders], { covered: 0, total: 0, missing: [] }).score;
    const after = projectScore([applyEffect(orders, { tableComment: true })], {
      covered: 0,
      total: 0,
      missing: [],
    }).score;
    expect(after).toBeGreaterThan(before);
  });
});
