import type { Application, Request } from 'express';
import { z } from 'zod';
import type { LakebasePool } from '@databricks/appkit';
import { validateSchema } from '../../shared/designer';
import type { Pattern, PatternPlan, PatternRun } from '../../shared/patterns';
import { compareRows, createStatement, dropStatement, sandboxSchema, sandboxViewName } from '../designer/validate';
import { SLUG, testQueryFor } from '../patterns/library';
import { runStatement } from '../sql/runner';
import type { RunDeps } from '../sql/runner';
import { projectRepo } from './projects';
import { actorOf, handle, HttpError } from './http';

type Db = Pick<LakebasePool, 'query' | 'connect'>;

interface RunRow {
  slug: string;
  status: PatternRun['status'];
  sandbox_view: string;
  rows_compared: number;
  detail: string | null;
  test_sql: string;
  created_by: string;
  created_at: Date;
}

const toRun = (r: RunRow): PatternRun => ({
  slug: r.slug,
  status: r.status,
  sandboxView: r.sandbox_view,
  rows: r.rows_compared,
  detail: r.detail,
  testSql: r.test_sql,
  cleanup: r.status === 'running' ? [] : [dropStatement(r.sandbox_view)],
  createdBy: r.created_by,
  createdAt: r.created_at.toISOString(),
});

export function patternRunRepo(db: Db) {
  return {
    /** Latest run per pattern for a project. */
    async latest(projectId: string): Promise<PatternRun[]> {
      const { rows } = await db.query<RunRow>(
        `SELECT DISTINCT ON (slug) slug, status, sandbox_view, rows_compared, detail, test_sql, created_by, created_at
         FROM gsb.pattern_run WHERE project_id = $1 ORDER BY slug, created_at DESC`,
        [projectId]
      );
      return rows.map(toRun);
    },

    async start(actor: string, projectId: string, slug: string, plan: PatternPlan, testSql: string) {
      const { rows } = await db.query<{ id: string }>(
        `WITH r AS (
           INSERT INTO gsb.pattern_run (project_id, slug, sandbox_view, statements, test_sql, created_by)
           VALUES ($1, $2, $3, $4::text[], $5, $6) RETURNING id
         ), a AS (
           INSERT INTO gsb.audit_log (actor, action, project_id, target, outcome, detail)
           SELECT $6, 'try_pattern', $1, $3, 'requested', jsonb_build_object('pattern', $2::text) FROM r
         )
         SELECT id FROM r`,
        [projectId, slug, plan.sandboxView, plan.statements, testSql, actor]
      );
      return rows[0].id;
    },

    async finish(id: string, status: 'passed' | 'failed', rows: number, detail: string) {
      await db.query(
        'UPDATE gsb.pattern_run SET status = $2, rows_compared = $3, detail = $4, finished_at = now() WHERE id = $1',
        [id, status, rows, detail]
      );
    },
  };
}

const params = z.object({ id: z.uuid(), slug: z.string().regex(SLUG) });
const sameStatements = (a: string[], b: string[]) => a.length === b.length && a.every((s, i) => s === b[i]);

export function registerPatternRoutes(
  app: Application,
  db: Db,
  patterns: Pattern[],
  runFor: (req: Request) => RunDeps
) {
  const projects = projectRepo(db);
  const runs = patternRunRepo(db);
  const bySlug = new Map(patterns.map((p) => [p.slug, p]));

  async function target(req: Request) {
    const actor = actorOf(req);
    const { id, slug } = params.parse(req.params);
    const project = await projects.get(actor, id);
    const pattern = bySlug.get(slug);
    if (!pattern) throw new HttpError(404, 'Pattern not found.');
    const sandbox = sandboxSchema();
    if (!sandbox) throw new HttpError(503, 'The sandbox schema is not configured for this app.');
    const sandboxView = sandboxViewName(sandbox, `pattern_${slug}`, project.id);
    const plan: PatternPlan = { sandboxView, statements: [createStatement(sandboxView, pattern.yaml)] };
    return { actor, project, pattern, plan };
  }

  app.get(
    '/api/patterns',
    handle((req) => {
      actorOf(req);
      return Promise.resolve(patterns);
    })
  );

  app.get(
    '/api/projects/:id/patterns/runs',
    handle(async (req) => {
      const project = await projects.get(actorOf(req), z.object({ id: z.uuid() }).parse(req.params).id);
      return runs.latest(project.id);
    })
  );

  app.get(
    '/api/projects/:id/patterns/:slug/try',
    handle(async (req): Promise<PatternPlan> => (await target(req)).plan)
  );

  app.post(
    '/api/projects/:id/patterns/:slug/try',
    handle(async (req): Promise<PatternRun | undefined> => {
      const { statements } = validateSchema.parse(req.body);
      const { actor, project, pattern, plan } = await target(req);
      if (!sameStatements(statements, plan.statements))
        throw new HttpError(409, 'The SQL changed since you reviewed it. Review it again.');
      const testSql = testQueryFor(pattern, plan.sandboxView);
      const runId = await runs.start(actor, project.id, pattern.slug, plan, testSql);
      const run = runFor(req);
      const ctx = { actor, projectId: project.id };
      try {
        for (const s of plan.statements) await runStatement(s, { ...ctx, approved: true }, run);
        const actual = await runStatement(testSql, { ...ctx, approved: false }, run);
        const { columns } = pattern.expected;
        const result = sameStatements(actual.columns, columns)
          ? compareRows(columns, actual.rows, pattern.expected.rows, 'the expected output')
          : { status: 'failed' as const, rows: 0, detail: 'The result columns differ from the expected output.' };
        await runs.finish(runId, result.status === 'passed' ? 'passed' : 'failed', result.rows, result.detail);
      } catch (err) {
        await runs.finish(runId, 'failed', 0, (err as Error).message.slice(0, 1000));
      }
      return (await runs.latest(project.id)).find((r) => r.slug === pattern.slug);
    })
  );

  app.post(
    '/api/projects/:id/patterns/:slug/try/drop',
    handle(async (req) => {
      const { statements } = validateSchema.parse(req.body);
      const { actor, project, pattern } = await target(req);
      const cleanup = (await runs.latest(project.id)).find((r) => r.slug === pattern.slug)?.cleanup ?? [];
      if (!cleanup.length || !sameStatements(statements, cleanup))
        throw new HttpError(409, 'The SQL changed since you reviewed it. Review it again.');
      for (const s of cleanup) await runStatement(s, { actor, projectId: project.id, approved: true }, runFor(req));
      return { removed: true };
    })
  );
}
