import { describe, expect, it } from 'vitest';
import { fixRows, finalFix, withoutTarget } from './edit';
import { fkStatement, pkStatements, sqlString } from './profile';
import type { TableProfile } from './profile';

const orders: TableProfile = {
  fullName: 'c.s.orders',
  comment: '',
  columns: [
    { name: 'o_orderkey', type: 'bigint', comment: '' },
    { name: 'o_custkey', type: 'bigint', comment: 'old text' },
  ],
  primaryKey: [],
  foreignKeys: [],
};
const customer: TableProfile = {
  fullName: 'c.s.customer',
  comment: 'Customers',
  columns: [{ name: 'c_custkey', type: 'bigint', comment: '' }],
  primaryKey: ['c_custkey'],
  foreignKeys: [],
};
const profiles = new Map([
  [orders.fullName, orders],
  [customer.fullName, customer],
]);
const colComments = [
  `COMMENT ON COLUMN \`c\`.\`s\`.\`orders\`.\`o_orderkey\` IS ${sqlString("The order's key")}`,
  `COMMENT ON COLUMN \`c\`.\`s\`.\`orders\`.\`o_custkey\` IS ${sqlString('The customer')}`,
];

describe('fixRows', () => {
  it('shows table, column, type, current and proposed text of comments', () => {
    expect(fixRows('column_comments', 'c.s.orders', colComments, profiles)).toEqual([
      {
        kind: 'comment',
        index: 0,
        table: 'c.s.orders',
        column: 'o_orderkey',
        type: 'bigint',
        current: '',
        proposed: "The order's key",
      },
      {
        kind: 'comment',
        index: 1,
        table: 'c.s.orders',
        column: 'o_custkey',
        type: 'bigint',
        current: 'old text',
        proposed: 'The customer',
      },
    ]);
  });
  it('shows the columns of a key with the options to pick from', () => {
    const [pk] = fixRows('primary_key', 'c.s.orders', pkStatements('c.s.orders', ['o_orderkey']), profiles);
    expect(pk).toMatchObject({ kind: 'key', columns: ['o_orderkey'], references: null });
    const [fk] = fixRows(
      'foreign_key',
      'c.s.orders',
      [fkStatement('c.s.orders', 'c.s.customer', ['o_custkey'], ['c_custkey'])],
      profiles
    );
    expect(fk).toMatchObject({ columns: ['o_custkey'], references: 'c.s.customer', refColumns: ['c_custkey'] });
    expect(fk.kind === 'key' && fk.refOptions).toEqual([{ name: 'c_custkey', type: 'bigint' }]);
  });
});

describe('finalFix', () => {
  it('keeps the proposal when nothing is edited', () => {
    expect(finalFix('column_comments', 'c.s.orders', colComments, {}, profiles)).toEqual({
      statements: colComments,
      effect: null,
    });
  });
  it('rebuilds edited comments, leaves out skipped rows, and updates the effect', () => {
    const out = finalFix(
      'column_comments',
      'c.s.orders',
      colComments,
      { comments: [null, "It's me"], skip: [0] },
      profiles
    );
    expect(out.statements).toEqual([`COMMENT ON COLUMN \`c\`.\`s\`.\`orders\`.\`o_custkey\` IS 'It\\'s me'`]);
    expect(out.effect).toEqual({ columns: ['o_custkey'] });
  });
  it('needs one change at least', () => {
    expect(() => finalFix('column_comments', 'c.s.orders', colComments, { skip: [0, 1] }, profiles)).toThrow(
      /at least one/
    );
  });
  it('rebuilds a key from real columns only', () => {
    const pk = pkStatements('c.s.orders', ['o_custkey']);
    expect(finalFix('primary_key', 'c.s.orders', pk, { key: { columns: ['O_ORDERKEY'] } }, profiles)).toEqual({
      statements: pkStatements('c.s.orders', ['o_orderkey']),
      effect: { primaryKey: ['o_orderkey'] },
    });
    expect(() =>
      finalFix('primary_key', 'c.s.orders', pk, { key: { columns: ['x; DROP TABLE y'] } }, profiles)
    ).toThrow(/distinct columns/);
    const fk = [fkStatement('c.s.orders', 'c.s.customer', ['o_custkey'], ['c_custkey'])];
    expect(() =>
      finalFix('foreign_key', 'c.s.orders', fk, { key: { columns: ['o_orderkey'], refColumns: [] } }, profiles)
    ).toThrow();
    expect(
      finalFix(
        'foreign_key',
        'c.s.orders',
        fk,
        { key: { columns: ['o_orderkey'], refColumns: ['c_custkey'] } },
        profiles
      ).statements
    ).toEqual([fkStatement('c.s.orders', 'c.s.customer', ['o_orderkey'], ['c_custkey'])]);
  });
});

describe('withoutTarget', () => {
  it('drops the statement of one column, by name or by index, and keeps the rest', () => {
    expect(withoutTarget('column_comments', colComments, { column: 'O_CUSTKEY' })).toEqual({
      statements: [colComments[0]],
      effect: { columns: ['o_orderkey'] },
    });
    expect(withoutTarget('column_comments', colComments, { index: 0 })?.statements).toEqual([colComments[1]]);
    expect(withoutTarget('column_comments', colComments, { column: 'other' })).toBeNull();
    expect(withoutTarget('primary_key', pkStatements('c.s.orders', ['o_orderkey']), { index: 0 })).toBeNull();
  });
});
