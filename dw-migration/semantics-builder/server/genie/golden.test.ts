import { describe, expect, it } from 'vitest';
import { golden } from './golden';
import type { SubFacts } from './golden';

const sub: SubFacts = {
  projectId: 'p1',
  name: 'Net revenue',
  view: 'c.s.v',
  version: 2,
  tables: 5,
  certified: 5,
  approved: true,
  run: { correct: 5, questions: 5, at: '2026-11-11T00:00:00Z' },
};

describe('golden', () => {
  it('is golden when the agent is up to date and every gate passes', () => {
    expect(golden({ exists: true, current: true }, [sub]).golden).toBe(true);
  });

  it('fails on one table not certified, no approval, low accuracy, or an old agent', () => {
    expect(golden({ exists: true, current: true }, [{ ...sub, certified: 4 }]).golden).toBe(false);
    expect(golden({ exists: true, current: true }, [{ ...sub, approved: false }]).golden).toBe(false);
    const low = golden({ exists: true, current: true }, [{ ...sub, run: { ...sub.run!, correct: 4 } }]);
    expect(low.golden).toBe(false);
    expect(low.subProjects[0].gates.find((g) => g.id === 'accuracy')?.detail).toMatch(/^80%/);
    expect(golden({ exists: true, current: false }, [sub]).golden).toBe(false);
    expect(golden(null, []).golden).toBe(false);
  });
});
