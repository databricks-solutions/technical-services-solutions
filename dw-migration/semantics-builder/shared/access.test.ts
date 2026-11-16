import { describe, expect, it } from 'vitest';
import { accessDifference } from './access';

const r = (status: 'passed' | 'failed' | 'error', rows: number) => ({ name: 't', status, rows, detail: '' });

describe('accessDifference', () => {
  it('reads a row filter, a value change and an error', () => {
    expect(accessDifference(r('passed', 10), r('passed', 10))).toBe('same');
    expect(accessDifference(r('passed', 10), r('passed', 4))).toBe('fewer_rows');
    expect(accessDifference(r('passed', 1), r('failed', 1))).toBe('other_value');
    expect(accessDifference(r('passed', 10), r('error', 0))).toBe('fails');
    expect(accessDifference(undefined, r('passed', 3))).toBe('no_owner_run');
  });
});
