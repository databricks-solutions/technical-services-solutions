import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';

export interface Migration {
  version: string;
  sql: string;
}

interface ClientLike {
  query(sql: string, params?: unknown[]): Promise<{ rows: unknown[] }>;
  release(): void;
}

export interface PoolLike {
  connect(): Promise<ClientLike>;
}

export const SCHEMA = 'gsb';
const FILE_PATTERN = /^(\d{3})_[a-z0-9_]+\.sql$/;

export async function loadMigrations(dir: string): Promise<Migration[]> {
  const files = (await readdir(dir)).filter((f) => f.endsWith('.sql')).sort();
  const seen = new Set<string>();
  const migrations: Migration[] = [];
  for (const file of files) {
    const match = FILE_PATTERN.exec(file);
    if (!match) throw new Error(`Migration file name must look like 001_name.sql: ${file}`);
    if (seen.has(match[1])) throw new Error(`Duplicate migration number ${match[1]}`);
    seen.add(match[1]);
    migrations.push({ version: file.slice(0, -4), sql: await readFile(path.join(dir, file), 'utf8') });
  }
  return migrations;
}

/** Applies pending migrations in one transaction. The advisory lock serializes concurrent app instances. */
export async function migrate(pool: PoolLike, migrations: Migration[]): Promise<string[]> {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    await client.query(`SELECT pg_advisory_xact_lock(hashtext('${SCHEMA}.migrate'))`);
    await client.query(`CREATE SCHEMA IF NOT EXISTS ${SCHEMA}`);
    await client.query(
      `CREATE TABLE IF NOT EXISTS ${SCHEMA}.schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())`
    );
    const { rows } = await client.query(`SELECT version FROM ${SCHEMA}.schema_migrations`);
    const done = new Set((rows as { version: string }[]).map((r) => r.version));
    const applied: string[] = [];
    for (const { version, sql } of migrations) {
      if (done.has(version)) continue;
      try {
        await client.query(sql);
      } catch (err) {
        throw new Error(`Migration ${version} failed: ${(err as Error).message}`);
      }
      await client.query(`INSERT INTO ${SCHEMA}.schema_migrations (version) VALUES ($1)`, [version]);
      applied.push(version);
    }
    await client.query('COMMIT');
    return applied;
  } catch (err) {
    await client.query('ROLLBACK');
    throw err;
  } finally {
    client.release();
  }
}
