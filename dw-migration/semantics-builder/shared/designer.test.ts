import { describe, expect, it } from 'vitest';
import { fieldExpr, saveDraftSchema } from './designer';

describe('fieldExpr', () => {
  it('builds measure aggregations on the fact table or a join chain', () => {
    expect(fieldExpr({ ref: 'source', column: 'o_totalprice', aggregation: 'SUM' })).toBe('SUM(source.o_totalprice)');
    expect(fieldExpr({ ref: 'dim_customer', column: 'c_custkey', aggregation: 'COUNT_DISTINCT' })).toBe(
      'COUNT(DISTINCT dim_customer.c_custkey)'
    );
    expect(fieldExpr({ ref: 'source', column: '', aggregation: 'COUNT' })).toBe('COUNT(1)');
  });

  it('builds dimensions with an optional date grain, and quotes odd column names', () => {
    expect(fieldExpr({ ref: 'dim_customer.dim_nation', column: 'n_name' })).toBe('dim_customer.dim_nation.n_name');
    expect(fieldExpr({ ref: 'source', column: 'o_orderdate', grain: 'MONTH' })).toBe(
      "DATE_TRUNC('MONTH', source.o_orderdate)"
    );
    expect(fieldExpr({ ref: 'source', column: 'order date' })).toBe('source.`order date`');
  });
});

describe('saveDraftSchema', () => {
  it('accepts edited tests and rejects a test with no measure', () => {
    const base = { baseVersion: 1, yaml: 'version: 1.1' };
    expect(
      saveDraftSchema.safeParse({ ...base, tests: [{ name: 'x', dimensions: [], measures: ['M'] }] }).success
    ).toBe(true);
    expect(saveDraftSchema.safeParse({ ...base, tests: [{ name: 'x', dimensions: [], measures: [] }] }).success).toBe(
      false
    );
  });
});
