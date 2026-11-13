import { cp, mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { validateMetricView } from '../../shared/metricView';
import { loadPatterns, testQueryFor } from './library';

const DIR = path.resolve('patterns');

describe('pattern library', () => {
  it('loads every pattern folder without errors', async () => {
    const { patterns, skipped } = await loadPatterns(DIR);
    expect(skipped).toEqual([]);
    expect(patterns.length).toBeGreaterThanOrEqual(18);
    for (const p of patterns) {
      expect(p.expected.rows.length, p.slug).toBeGreaterThan(0);
      const { view } = validateMetricView(p.yaml);
      const names = new Set([...view!.dimensions, ...view!.measures].map((f) => f.name));
      expect(p.test.query, p.slug).toMatch(/\bMEASURE\(/);
      for (const [, ref] of p.test.query.matchAll(/MEASURE\(`([^`]+)`\)/g)) expect(names, p.slug).toContain(ref);
    }
  });

  it('skips a folder that is not valid and keeps the rest', async () => {
    const dir = await mkdtemp(path.join(tmpdir(), 'gsb-patterns-'));
    await cp(path.join(DIR, 'ranking'), path.join(dir, 'ranking'), { recursive: true });
    await cp(path.join(DIR, 'ranking'), path.join(dir, 'broken'), { recursive: true });
    await writeFile(path.join(dir, 'broken', 'metric_view.yml'), 'version: 1.1\nsource: a.b.c\n');
    await cp(path.join(DIR, 'ranking'), path.join(dir, 'Bad-Name'), { recursive: true });
    const { patterns, skipped } = await loadPatterns(dir);
    expect(patterns.map((p) => p.slug)).toEqual(['ranking']);
    expect(skipped).toEqual([
      expect.stringMatching(/^Bad-Name: folder name/),
      expect.stringMatching(/^broken: metric_view.yml: line 1: /),
    ]);
  });

  it('puts the quoted sandbox view into the test query', () => {
    expect(testQueryFor({ test: { query: 'SELECT 1 FROM {{view}} UNION ALL SELECT 2 FROM {{view}}' } }, 'a.b.c')).toBe(
      'SELECT 1 FROM `a`.`b`.`c` UNION ALL SELECT 2 FROM `a`.`b`.`c`'
    );
  });
});
