import { describe, expect, it } from 'vitest';
import { mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { loadMigrations, migrate } from './migrate';
import type { Migration, PoolLike } from './migrate';

function fakePool(applied: string[] = [], failOn?: string) {
  const log: string[] = [];
  let released = false;
  const pool: PoolLike = {
    connect: () =>
      Promise.resolve({
        query: (sql: string, params?: unknown[]) => {
          log.push(params ? `${sql} ${JSON.stringify(params)}` : sql);
          if (failOn && sql.includes(failOn)) return Promise.reject(new Error('boom'));
          if (sql.startsWith('SELECT version'))
            return Promise.resolve({ rows: applied.map((version) => ({ version })) });
          return Promise.resolve({ rows: [] });
        },
        release: () => {
          released = true;
        },
      }),
  };
  return { pool, log, isReleased: () => released };
}

const m = (version: string, sql = `-- ${version}`): Migration => ({ version, sql });

describe('migrate', () => {
  it('applies pending migrations in order inside one locked transaction', async () => {
    const { pool, log, isReleased } = fakePool(['001_init']);
    const applied = await migrate(pool, [m('001_init'), m('002_more'), m('003_last')]);

    expect(applied).toEqual(['002_more', '003_last']);
    expect(log[0]).toBe('BEGIN');
    expect(log[1]).toContain('pg_advisory_xact_lock');
    expect(log).not.toContain('-- 001_init');
    expect(log.indexOf('-- 002_more')).toBeLessThan(log.indexOf('-- 003_last'));
    expect(log[log.length - 1]).toBe('COMMIT');
    expect(isReleased()).toBe(true);
  });

  it('does nothing but commit when all migrations are applied', async () => {
    const { pool, log } = fakePool(['001_init']);
    expect(await migrate(pool, [m('001_init')])).toEqual([]);
    expect(log[log.length - 1]).toBe('COMMIT');
  });

  it('rolls back and rethrows when a migration fails', async () => {
    const { pool, log, isReleased } = fakePool([], 'bad');
    await expect(migrate(pool, [m('001_init'), m('002_bad', 'bad sql')])).rejects.toThrow('002_bad');
    expect(log[log.length - 1]).toBe('ROLLBACK');
    expect(log.some((l) => l.includes('INSERT INTO'))).toBe(true);
    expect(isReleased()).toBe(true);
  });
});

describe('loadMigrations', () => {
  async function dirWith(files: Record<string, string>) {
    const dir = await mkdtemp(path.join(tmpdir(), 'gsb-mig-'));
    await Promise.all(Object.entries(files).map(([n, c]) => writeFile(path.join(dir, n), c)));
    return dir;
  }

  it('loads numbered .sql files sorted by version', async () => {
    const dir = await dirWith({ '002_b.sql': 'B', '001_a.sql': 'A', 'README.md': 'x' });
    expect(await loadMigrations(dir)).toEqual([
      { version: '001_a', sql: 'A' },
      { version: '002_b', sql: 'B' },
    ]);
  });

  it('rejects badly named sql files and duplicate numbers', async () => {
    await expect(loadMigrations(await dirWith({ 'init.sql': 'A' }))).rejects.toThrow('init.sql');
    await expect(loadMigrations(await dirWith({ '001_a.sql': 'A', '001_b.sql': 'B' }))).rejects.toThrow('001');
  });
});
