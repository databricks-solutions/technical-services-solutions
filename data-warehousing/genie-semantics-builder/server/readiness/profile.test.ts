import { describe, expect, it } from 'vitest';
import { checkStatement } from '../sql/allowlist';
import { profileFromTable } from '../uc/metadata';
import type { UcTableInfo } from '../uc/metadata';
import { buildRecommendations, checksFor } from './profile';
import type { TableProfile } from './profile';

// The shape the Unity Catalog tables API returns.
const ORDERS: UcTableInfo = {
  comment: 'Customer orders',
  columns: [
    { name: 'o_orderkey', type_text: 'bigint' },
    { name: 'o_custkey', type_text: 'bigint', comment: 'Customer key' },
    { name: 'o_orderdate', type_text: 'string' },
  ],
  table_constraints: [
    { primary_key_constraint: { child_columns: ['o_orderkey'] } },
    {
      foreign_key_constraint: {
        child_columns: ['o_custkey'],
        parent_table: 'sandbox.gsb.customer',
        parent_columns: ['c_custkey'],
      },
    },
  ],
};

const customer: TableProfile = {
  fullName: 'sandbox.gsb.customer',
  comment: '',
  columns: [
    { name: 'c_custkey', type: 'bigint', comment: '' },
    { name: 'c_nationkey', type: 'bigint', comment: '' },
  ],
  primaryKey: [],
  foreignKeys: [],
};
const nation: TableProfile = {
  ...customer,
  fullName: 'sandbox.gsb.nation',
  columns: [{ name: 'n_nationkey', type: 'bigint', comment: '' }],
};

describe('profileFromTable', () => {
  it('reads columns, the table comment and constraints', () => {
    const p = profileFromTable('sandbox.gsb.orders', ORDERS);
    expect(p.columns.map((c) => c.name)).toEqual(['o_orderkey', 'o_custkey', 'o_orderdate']);
    expect(p.comment).toBe('Customer orders');
    expect(p.primaryKey).toEqual(['o_orderkey']);
    expect(p.foreignKeys).toEqual([
      { columns: ['o_custkey'], references: 'sandbox.gsb.customer', refColumns: ['c_custkey'] },
    ]);
  });

  it('flags missing comments and dates stored as text', () => {
    const checks = Object.fromEntries(
      checksFor(profileFromTable('sandbox.gsb.orders', ORDERS)).map((c) => [c.id, c.status])
    );
    expect(checks).toMatchObject({
      table_comment: 'pass',
      column_comments: 'warn',
      primary_key: 'pass',
      foreign_keys: 'pass',
      date_types: 'warn',
    });
  });
});

describe('buildRecommendations', () => {
  const others = new Map([['sandbox.gsb.nation', nation]]);
  const recs = buildRecommendations(
    customer,
    {
      tableComment: "Customers'; DROP TABLE x --",
      columnComments: [
        { column: 'C_CUSTKEY', comment: 'Customer key \\ id' },
        { column: 'c_custkey', comment: 'duplicate' },
        { column: 'invented', comment: 'Not a real column' },
      ],
      primaryKey: ['c_custkey'],
      foreignKeys: [
        { columns: ['c_nationkey'], references: 'sandbox.gsb.nation', refColumns: ['n_nationkey'] },
        { columns: ['c_nationkey'], references: 'sandbox.gsb.invented', refColumns: ['x'] },
        { columns: ['c_custkey', 'c_nationkey'], references: 'sandbox.gsb.nation', refColumns: ['n_nationkey'] },
      ],
    },
    others
  );

  it('keeps only proposals that match real columns and tables', () => {
    expect(recs.map((r) => r.kind)).toEqual(['table_comment', 'column_comments', 'primary_key', 'foreign_key']);
    expect(recs[1].statements).toHaveLength(1);
    expect(recs[2].statements).toEqual([
      'ALTER TABLE `sandbox`.`gsb`.`customer` ALTER COLUMN `c_custkey` SET NOT NULL',
      'ALTER TABLE `sandbox`.`gsb`.`customer` ADD CONSTRAINT `customer_pk` PRIMARY KEY (`c_custkey`)',
    ]);
  });

  it('produces single, allowlisted DDL statements even for hostile text', () => {
    for (const s of recs.flatMap((r) => r.statements)) expect(checkStatement(s)).toEqual({ kind: 'ddl', statement: s });
    expect(recs[0].statements[0]).toBe(
      "COMMENT ON TABLE `sandbox`.`gsb`.`customer` IS 'Customers\\'; DROP TABLE x --'"
    );
  });

  it('does not repeat what the table already has', () => {
    const done = { ...customer, comment: 'x', primaryKey: ['c_custkey'] };
    const again = buildRecommendations(
      done,
      { tableComment: 'y', columnComments: [], primaryKey: ['c_custkey'], foreignKeys: [] },
      others
    );
    expect(again).toEqual([]);
  });
});
