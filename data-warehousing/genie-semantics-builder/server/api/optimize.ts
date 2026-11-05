import type { Application, Request } from 'express';
import { z } from 'zod';
import type { LakebasePool } from '@databricks/appkit';
import { validateMetricView } from '../../shared/metricView';
import type { MetricView } from '../../shared/metricView';
import type {
  OptimizeView,
  StressAttempt,
  StressQueryResult,
  StressRun,
  StressSettings,
  StressStatus,
  WorkloadQuery,
} from '../../shared/optimize';
import { createStatement, sandboxSchema, sandboxViewName } from '../designer/validate';
import { buildWorkload, MAX_QUERIES, MAX_REPEATS, stressSql, summarize } from '../optimize/workload';
import { runStatement } from '../sql/runner';
import type { RunDeps } from '../sql/runner';
import type { UcDeps } from '../uc/metadata';
import { actorOf, handle, HttpError } from './http';
import { designerRepo } from './designer';
import { projectRepo } from './projects';

type Db = Pick<LakebasePool, 'query' | 'connect'>;

const TIMEOUT_SECONDS = 50;
const METRICS_WAIT_MS = 30_000;

const name = z.string().trim().min(1).max(255);
const runSchema = z.strictObject({
  version: z.number().int().positive(),
  queries: z
    .array(
      z.strictObject({
        label: z.string().trim().min(1).max(200),
        dimensions: z.array(name).max(10),
        measures: z.array(name).min(1).max(30),
        origin: z.enum(['test', 'generated', 'custom']),
      })
    )
    .min(1)
    .max(MAX_QUERIES),
  settings: z.strictObject({
    repeats: z.number().int().min(1).max(MAX_REPEATS),
    targetMs: z.number().int().min(100).max(600_000),
  }),
  /** The setup statements the user reviewed. */
  statements: z.array(z.string()).max(5),
});
const idParam = z.object({ id: z.uuid() });
const runParam = idParam.extend({ runId: z.uuid() });

interface RunRow {
  id: string;
  version: number;
  sandbox_view: string;
  settings: StressSettings;
  status: StressStatus;
  error: string | null;
  created_by: string;
  created_at: Date;
  finished_at: Date | null;
}

function toResult(q: WorkloadQuery, sql: string, attempts: StressAttempt[], targetMs: number): StressQueryResult {
  return { ...q, sql, attempts, ...summarize(attempts, targetMs) };
}

/** Names in a request must be fields of the view, so the SQL is built from known names only. */
function checkFields(view: MetricView, q: WorkloadQuery) {
  const dims = new Set(view.dimensions.map((d) => d.name));
  const measures = new Set(view.measures.map((m) => m.name));
  const bad = [...q.dimensions.filter((d) => !dims.has(d)), ...q.measures.filter((m) => !measures.has(m))];
  if (bad.length) throw new HttpError(400, `Not in the metric view: ${bad.join(', ')}.`);
}

export function stressRepo(db: Db) {
  return {
    async latest(projectId: string): Promise<StressRun | null> {
      const { rows } = await db.query<RunRow>(
        `SELECT id, version, sandbox_view, settings, status, error, created_by, created_at, finished_at
         FROM gsb.stress_run r WHERE project_id = $1
           AND (status IN ('running', 'stopping', 'failed')
             OR EXISTS (SELECT 1 FROM gsb.stress_query q WHERE q.run_id = r.id AND q.attempts <> '[]'::jsonb))
         ORDER BY created_at DESC LIMIT 1`,
        [projectId]
      );
      const run = rows[0];
      if (!run) return null;
      const queries = await db.query<{ query: WorkloadQuery; sql: string; attempts: StressAttempt[] }>(
        'SELECT query, sql, attempts FROM gsb.stress_query WHERE run_id = $1 ORDER BY position',
        [run.id]
      );
      return {
        id: run.id,
        version: run.version,
        sandboxView: run.sandbox_view,
        settings: run.settings,
        status: run.status,
        error: run.error,
        createdBy: run.created_by,
        createdAt: run.created_at.toISOString(),
        finishedAt: run.finished_at?.toISOString() ?? null,
        queries: queries.rows.map((r) => toResult(r.query, r.sql, r.attempts, run.settings.targetMs)),
      };
    },

    async start(
      actor: string,
      projectId: string,
      version: number,
      sandboxView: string,
      settings: StressSettings,
      queries: { query: WorkloadQuery; sql: string }[]
    ): Promise<string> {
      const client = await db.connect();
      try {
        await client.query('BEGIN');
        // A run longer than the worst case (all queries at the timeout) died with an app restart.
        await client.query(
          `UPDATE gsb.stress_run SET status = 'failed', error = 'The app restarted during the run.', finished_at = now()
           WHERE project_id = $1 AND status IN ('running', 'stopping') AND created_at < now() - interval '2 hours'`,
          [projectId]
        );
        const { rows } = await client
          .query<{ id: string }>(
            `INSERT INTO gsb.stress_run (project_id, version, sandbox_view, settings, created_by)
             VALUES ($1, $2, $3, $4, $5) RETURNING id`,
            [projectId, version, sandboxView, settings, actor]
          )
          .catch((err: unknown) => {
            if ((err as { code?: string }).code === '23505')
              throw new HttpError(409, 'A stress test is already running for this sub-project.');
            throw err;
          });
        const id = rows[0].id;
        for (const [i, q] of queries.entries())
          await client.query('INSERT INTO gsb.stress_query (run_id, position, query, sql) VALUES ($1, $2, $3, $4)', [
            id,
            i,
            q.query,
            q.sql,
          ]);
        await client.query('COMMIT');
        return id;
      } catch (err) {
        await client.query('ROLLBACK');
        throw err;
      } finally {
        client.release();
      }
    },

    async status(runId: string): Promise<StressStatus> {
      const { rows } = await db.query<{ status: StressStatus }>('SELECT status FROM gsb.stress_run WHERE id = $1', [
        runId,
      ]);
      return rows[0]?.status ?? 'failed';
    },

    saveAttempts: (runId: string, position: number, attempts: StressAttempt[]) =>
      db.query('UPDATE gsb.stress_query SET attempts = $3 WHERE run_id = $1 AND position = $2', [
        runId,
        position,
        JSON.stringify(attempts),
      ]),

    finish: (runId: string, status: 'stopped' | 'finished' | 'failed', error?: string) =>
      db.query('UPDATE gsb.stress_run SET status = $2, error = $3, finished_at = now() WHERE id = $1', [
        runId,
        status,
        error ?? null,
      ]),

    async stop(projectId: string, runId: string) {
      const { rows } = await db.query(
        `UPDATE gsb.stress_run SET status = 'stopping' WHERE id = $1 AND project_id = $2 AND status = 'running'
         RETURNING id`,
        [runId, projectId]
      );
      if (!rows.length) throw new HttpError(409, 'This stress test is not running.');
    },
  };
}

/** Runs the queries one by one, then reads their metrics. Stops between statements when asked. */
async function execute(
  repo: ReturnType<typeof stressRepo>,
  runId: string,
  ctx: { actor: string; projectId: string },
  setup: string[],
  queries: { query: WorkloadQuery; sql: (tag: number) => string }[],
  settings: StressSettings,
  run: RunDeps,
  uc: UcDeps
) {
  try {
    for (const s of setup) await runStatement(s, { ...ctx, approved: true }, run);
  } catch (err) {
    await repo.finish(runId, 'failed', `Creating the sandbox view failed: ${(err as Error).message.slice(0, 1000)}`);
    return;
  }
  const all: StressAttempt[][] = queries.map(() => []);
  let stopped = false;
  let tag = Date.now();
  outer: for (const [i, q] of queries.entries()) {
    for (let r = 0; r < settings.repeats; r++) {
      if ((await repo.status(runId)) !== 'running') {
        stopped = true;
        break outer;
      }
      const start = Date.now();
      try {
        const res = await runStatement(q.sql(tag++), { ...ctx, approved: false }, run);
        all[i].push({ statementId: res.statementId, wallMs: Date.now() - start });
      } catch (err) {
        all[i].push({ wallMs: Date.now() - start, error: (err as Error).message.slice(0, 500) });
      }
      await repo.saveAttempts(runId, i, all[i]);
    }
  }

  const ids = all.flat().flatMap((a) => (a.statementId ? [a.statementId] : []));
  const metrics = new Map<string, Omit<StressAttempt, 'wallMs'>>();
  const deadline = Date.now() + METRICS_WAIT_MS;
  try {
    while (metrics.size < ids.length && Date.now() < deadline) {
      for (const [k, v] of await uc.queryMetrics(ids.filter((id) => !metrics.has(id)))) metrics.set(k, v);
      if (metrics.size < ids.length) await new Promise((r) => setTimeout(r, 3000));
    }
  } catch (err) {
    console.warn(`Query History for stress run ${runId}: ${(err as Error).message.slice(0, 200)}`);
  }
  for (const [i, attempts] of all.entries()) {
    const merged = attempts.map((a) => ({ ...a, ...(a.statementId ? metrics.get(a.statementId) : {}) }));
    await repo.saveAttempts(runId, i, merged);
  }
  await repo.finish(runId, stopped ? 'stopped' : 'finished');
}

export function registerOptimizeRoutes(
  app: Application,
  db: Db,
  runFor: (req: Request) => RunDeps,
  ucFor: (req: Request) => UcDeps
) {
  const projects = projectRepo(db);
  const designs = designerRepo(db);
  const repo = stressRepo(db);

  async function context(req: Request) {
    const actor = actorOf(req);
    const project = await projects.get(actor, idParam.parse(req.params).id);
    const draft = (await designs.view(project.id)).draft;
    const view = draft ? validateMetricView(draft.yaml).view : undefined;
    const sandbox = sandboxSchema();
    const sandboxView = draft && sandbox ? sandboxViewName(sandbox, draft.name, project.id) : null;
    return { actor, project, draft, view, sandboxView };
  }

  app.get(
    '/api/projects/:id/optimize',
    handle(async (req): Promise<OptimizeView> => {
      const { project, draft, view, sandboxView } = await context(req);
      return {
        draft: draft ? { version: draft.version, name: draft.name, status: draft.status } : null,
        workload: view && draft ? buildWorkload(view, draft.tests) : [],
        view: view
          ? { dimensions: view.dimensions.map((d) => d.name), measures: view.measures.map((m) => m.name) }
          : null,
        setup: draft && sandboxView ? { sandboxView, statements: [createStatement(sandboxView, draft.yaml)] } : null,
        limits: { maxQueries: MAX_QUERIES, maxRepeats: MAX_REPEATS, timeoutSeconds: TIMEOUT_SECONDS },
        latest: await repo.latest(project.id),
      };
    })
  );

  app.post(
    '/api/projects/:id/optimize/runs',
    handle(async (req) => {
      const body = runSchema.parse(req.body);
      const { actor, project, draft, view, sandboxView } = await context(req);
      if (!draft || !view || draft.version !== body.version)
        throw new HttpError(409, 'The design changed. Reload the page.');
      if (draft.status !== 'validated') throw new HttpError(409, 'Validate the design before you stress test it.');
      if (!sandboxView) throw new HttpError(503, 'The sandbox schema is not configured.');
      const setup = [createStatement(sandboxView, draft.yaml)];
      if (body.statements.length !== setup.length || body.statements.some((s, i) => s !== setup[i]))
        throw new HttpError(409, 'The SQL changed since you reviewed it. Review it again.');
      for (const q of body.queries) checkFields(view, q);

      const queries = body.queries.map((query) => ({
        query,
        sql: (tag: number) => stressSql(sandboxView, query, tag),
      }));
      const runId = await repo.start(
        actor,
        project.id,
        draft.version,
        sandboxView,
        body.settings,
        queries.map((q) => ({ query: q.query, sql: q.sql(0) }))
      );
      // The run outlives the request; it keeps the user's identity for every statement.
      void execute(
        repo,
        runId,
        { actor, projectId: project.id },
        setup,
        queries,
        body.settings,
        runFor(req),
        ucFor(req)
      ).catch(async (err: unknown) => {
        console.error(`Stress run ${runId} failed`, err);
        await repo.finish(runId, 'failed', (err as Error).message.slice(0, 1000)).catch(() => undefined);
      });
      return { runId };
    })
  );

  app.post(
    '/api/projects/:id/optimize/runs/:runId/stop',
    handle(async (req) => {
      const { id, runId } = runParam.parse(req.params);
      const project = await projects.get(actorOf(req), id);
      await repo.stop(project.id, runId);
      return { stopping: true };
    })
  );
}
