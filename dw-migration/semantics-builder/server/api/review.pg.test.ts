import path from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import pg from 'pg';
import { loadMigrations, migrate } from '../db/migrate';
import { projectRepo } from './projects';
import { reviewRepo } from './review';

// Runs only against a throwaway Postgres: TEST_DATABASE_URL=postgres://... pnpm test
const url = process.env.TEST_DATABASE_URL;

describe.skipIf(!url)('reviewRepo on Postgres', () => {
  const pool = new pg.Pool({ connectionString: url });
  const projects = projectRepo(pool as never);
  const reviews = reviewRepo(pool as never);
  let sub = '';

  beforeAll(async () => {
    await pool.query('DROP SCHEMA IF EXISTS gsb CASCADE');
    await migrate(pool, await loadMigrations(path.resolve('server/db/migrations')));
    const parent = await projects.create('author@x.com', { name: 'Sales' });
    sub = (await projects.create('author@x.com', { name: 'Revenue' }, parent.id)).id;
  });
  afterAll(() => pool.end());

  const request = (version: number, reviewer = 'rev@x.com') =>
    pool.query<{ id: string }>(
      `INSERT INTO gsb.review (project_id, version, reviewer, requested_by) VALUES ($1, $2, $3, 'author@x.com')
       RETURNING id`,
      [sub, version, reviewer]
    );

  it('blocks Promote only when approval is required and the version is not approved', async () => {
    expect(await reviews.gate(sub, 1)).toBeNull();
    await pool.query('UPDATE gsb.project SET require_approval = true WHERE id = $1', [sub]);
    expect(await reviews.gate(sub, 1)).toBe('Version 1 needs approval by a reviewer before Promote.');
    const { rows } = await request(1);
    expect((await reviews.state(sub)).review).toMatchObject({
      status: 'pending',
      subProject: 'Revenue',
      project: 'Sales',
    });
    await pool.query(`UPDATE gsb.review SET status = 'approved' WHERE id = $1`, [rows[0].id]);
    expect(await reviews.gate(sub, 1)).toBeNull();
    expect(await reviews.gate(sub, 2)).not.toBeNull();
  });

  it('allows one pending review per sub-project, and no self-review', async () => {
    await request(2);
    await expect(request(2, 'other@x.com')).rejects.toThrow(/review_one_pending/);
    await expect(request(3, 'AUTHOR@x.com')).rejects.toThrow(/check/);
  });

  it('shows a review only to its reviewer and author, with any email case', async () => {
    const { rows } = await pool.query<{ id: string }>(`SELECT id FROM gsb.review WHERE status = 'pending'`);
    const id = rows[0].id;
    expect((await reviews.get('REV@x.com', id)).reviewer).toBe('rev@x.com');
    expect((await reviews.get('author@x.com', id)).id).toBe(id);
    await expect(reviews.get('someone@x.com', id)).rejects.toThrow('Review not found.');
  });
});
