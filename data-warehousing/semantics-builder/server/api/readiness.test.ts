import { describe, expect, it } from 'vitest';
import { joinGroups } from './readiness';

describe('joinGroups', () => {
  it('groups tables by joins, largest first', () => {
    const links = [
      { from: 'a.b.lineitem', column: 'l_orderkey', to: 'a.b.orders', refColumn: 'o_orderkey' },
      { from: 'a.b.orders', column: 'o_custkey', to: 'a.b.customer', refColumn: 'c_custkey' },
    ];
    expect(joinGroups(['a.b.customer', 'a.b.trips', 'a.b.orders', 'a.b.lineitem'], links)).toEqual([
      ['a.b.customer', 'a.b.orders', 'a.b.lineitem'],
      ['a.b.trips'],
    ]);
  });
});
