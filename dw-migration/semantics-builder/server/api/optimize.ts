import type { Application, Request } from 'express';
import { z } from 'zod';
import type { LakebasePool } from '@databricks/appkit';
import { renderMetricView, validateMetricView } from '../../shared/metricView';
import type { MetricView } from '../../shared/metricView';
import { SCHEDULES } from '../../shared/optimize';
import type {
  BilledDbus,
  CostView,
  MaterializationTry,
  OptimizeView,
  StressAttempt,
  StressQueryResult,
  StressRun,
  StressSettings,
  StressStatus,
  TryPlan,
  WorkloadQuery,
} from '../../shared/optimize';
import { createStatement, dropStatement, sandboxSchema, sandboxViewName } from '../designer/validate';
import { matchedName, suggestMaterializations, withMaterialization } from '../optimize/materialize';
import { bestPractices } from '../optimize/practices';
import { budgetCheck, costOf, monthStart, usedThisMonth } from '../optimize/cost';
import { quoteName } from '../readiness/profile';
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
const REFRESH_WAIT_MS = 20 * 60_000;
const ACTIVE = `('running', 'refreshing', 'stopping')`;

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
const trySchema = z.strictObject({
  version: z.number().int().positive(),
  schedule: z.enum(SCHEDULES),
  views: z.array(name).min(1).max(5),
  statements: z.array(z.string()).max(5),
});
const planQuery = z.object({ schedule: z.enum(SCHEDULES), views: z.string().min(1).max(2000) });
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
  materialization: MaterializationTry | null;
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
    async load(run: RunRow): Promise<StressRun> {
      const queries = await db.query<{
        query: WorkloadQuery;
        sql: string;
        attempts: StressAttempt[];
        matched: string | null;
      }>('SELECT query, sql, attempts, matched FROM gsb.stress_query WHERE run_id = $1 ORDER BY position', [run.id]);
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
        queries: queries.rows.map((r) => ({
          ...toResult(r.query, r.sql, r.attempts, run.settings.targetMs),
          ...(run.materialization ? { matched: r.matched } : {}),
        })),
        materialization: run.materialization,
      };
    },

    /** The newest base run, or with tries, the newest materialization try. Empty stopped runs are skipped. */
    async latest(projectId: string, tries = false): Promise<StressRun | null> {
      const { rows } = await db.query<RunRow>(
        `SELECT id, version, sandbox_view, settings, status, error, created_by, created_at, finished_at, materialization
         FROM gsb.stress_run r WHERE project_id = $1 AND (materialization IS NOT NULL) = $2
           AND (status IN ('running', 'refreshing', 'stopping', 'failed')
             OR EXISTS (SELECT 1 FROM gsb.stress_query q WHERE q.run_id = r.id AND q.attempts <> '[]'::jsonb))
         ORDER BY created_at DESC LIMIT 1`,
        [projectId, tries]
      );
      return rows[0] ? this.load(rows[0]) : null;
    },

    /** The last 100 runs and tries, newest first, for the cost view and the budget. */
    async history(projectId: string): Promise<StressRun[]> {
      const { rows } = await db.query<RunRow>(
        `SELECT id, version, sandbox_view, settings, status, error, created_by, created_at, finished_at, materialization
         FROM gsb.stress_run WHERE project_id = $1 ORDER BY created_at DESC LIMIT 100`,
        [projectId]
      );
      return Promise.all(rows.map((r) => this.load(r)));
    },

    async budget(projectId: string): Promise<number | null> {
      const { rows } = await db.query<{ stress_budget_ms: string | null }>(
        'SELECT stress_budget_ms FROM gsb.project WHERE id = $1',
        [projectId]
      );
      return rows[0]?.stress_budget_ms ? Number(rows[0].stress_budget_ms) : null;
    },

    setBudget: (projectId: string, ms: number | null) =>
      db.query('UPDATE gsb.project SET stress_budget_ms = $2 WHERE id = $1', [projectId, ms]),

    async start(
      actor: string,
      projectId: string,
      version: number,
      sandboxView: string,
      settings: StressSettings,
      queries: { query: WorkloadQuery; sql: string }[],
      materialization: MaterializationTry | null = null
    ): Promise<string> {
      const client = await db.connect();
      try {
        await client.query('BEGIN');
        // A run longer than the worst case (all queries at the timeout) died with an app restart.
        await client.query(
          `UPDATE gsb.stress_run SET status = 'failed', error = 'The app restarted during the run.', finished_at = now()
           WHERE project_id = $1 AND status IN ${ACTIVE} AND created_at < now() - interval '2 hours'`,
          [projectId]
        );
        const { rows } = await client
          .query<{ id: string }>(
            `INSERT INTO gsb.stress_run (project_id, version, sandbox_view, settings, created_by, materialization, status)
             VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id`,
            [
              projectId,
              version,
              sandboxView,
              settings,
              actor,
              materialization,
              materialization ? 'refreshing' : 'running',
            ]
          )
          .catch((err: unknown) => {
            if ((err as { code?: string }).code === '23505')
              throw new HttpError(409, 'A stress test or materialization try is already running for this sub-project.');
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

    saveMatched: (runId: string, position: number, matched: string | null) =>
      db.query('UPDATE gsb.stress_query SET matched = $3 WHERE run_id = $1 AND position = $2', [
        runId,
        position,
        matched,
      ]),

    patchMaterialization: (runId: string, patch: Partial<MaterializationTry>) =>
      db.query('UPDATE gsb.stress_run SET materialization = materialization || $2::jsonb WHERE id = $1', [
        runId,
        JSON.stringify(patch),
      ]),

    /** From refreshing to running; false when the user stopped it meanwhile. */
    async refreshed(runId: string) {
      const { rows } = await db.query(
        `UPDATE gsb.stress_run SET status = 'running' WHERE id = $1 AND status = 'refreshing' RETURNING id`,
        [runId]
      );
      return rows.length > 0;
    },

    async run(projectId: string, runId: string): Promise<RunRow> {
      const { rows } = await db.query<RunRow>(
        `SELECT id, version, sandbox_view, settings, status, error, created_by, created_at, finished_at, materialization
         FROM gsb.stress_run WHERE id = $1 AND project_id = $2`,
        [runId, projectId]
      );
      if (!rows[0]) throw new HttpError(404, 'Run not found.');
      return rows[0];
    },

    finish: (runId: string, status: 'stopped' | 'finished' | 'failed', error?: string) =>
      db.query('UPDATE gsb.stress_run SET status = $2, error = $3, finished_at = now() WHERE id = $1', [
        runId,
        status,
        error ?? null,
      ]),

    async stop(projectId: string, runId: string) {
      const { rows } = await db.query(
        `UPDATE gsb.stress_run SET status = 'stopping'
         WHERE id = $1 AND project_id = $2 AND status IN ('running', 'refreshing')
         RETURNING id`,
        [runId, projectId]
      );
      if (!rows.length) throw new HttpError(409, 'This stress test is not running.');
    },
  };
}

const PIPELINE_URL = /https:\/\/\S+?\/pipelines\/[0-9a-f-]{36}(?:\/updates\/[0-9a-f-]{36})?/;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Polls DESCRIBE EXTENDED, which needs only the sql scope, until the first refresh ends. */
async function waitForRefresh(
  repo: ReturnType<typeof stressRepo>,
  runId: string,
  matView: string,
  exec: (sql: string) => Promise<{ rows: (string | null)[][] }>
): Promise<string | null> {
  const deadline = Date.now() + REFRESH_WAIT_MS;
  while (Date.now() < deadline) {
    if ((await repo.status(runId)) !== 'refreshing') return 'stopped';
    const { rows } = await exec(`DESCRIBE EXTENDED ${quoteName(matView)}`);
    const status = rows.find((r) => r[0]?.trim() === 'Latest Refresh Status')?.[1]?.trim() ?? '';
    if (/^succeeded$/i.test(status)) return null;
    if (/^(failed|canceled|cancelled)$/i.test(status)) return `The first refresh ${status.toLowerCase()}.`;
    await sleep(10_000);
  }
  return 'The first refresh did not finish in 20 minutes.';
}

interface ExecuteOptions {
  repo: ReturnType<typeof stressRepo>;
  runId: string;
  ctx: { actor: string; projectId: string };
  setup: string[];
  queries: { query: WorkloadQuery; sql: (tag: number) => string }[];
  settings: StressSettings;
  run: RunDeps;
  uc: UcDeps;
  /** For a materialization try: the view to wait on and the materialization names to look for. */
  materialization?: { matView: string; names: string[] };
  /** Warehouse time left in the monthly budget. The run stops when it is spent. */
  budgetLeftMs?: number | null;
}

/** Runs the queries one by one, then reads their metrics. Stops between statements when asked. */
async function execute({
  repo,
  runId,
  ctx,
  setup,
  queries,
  settings,
  run,
  uc,
  materialization,
  budgetLeftMs,
}: ExecuteOptions) {
  const read = (sql: string) => runStatement(sql, { ...ctx, approved: false }, run);
  try {
    for (const s of setup) {
      const res = await runStatement(s, { ...ctx, approved: true }, run);
      const url = res.rows.flat().join(' ').match(PIPELINE_URL)?.[0];
      if (url) await repo.patchMaterialization(runId, { pipelineUrl: url });
    }
  } catch (err) {
    await repo.finish(runId, 'failed', `Creating the sandbox view failed: ${(err as Error).message.slice(0, 1000)}`);
    return;
  }

  if (materialization) {
    const started = Date.now();
    const problem = await waitForRefresh(repo, runId, materialization.matView, read);
    if (problem === 'stopped' || (!problem && !(await repo.refreshed(runId)))) {
      await repo.finish(runId, 'stopped');
      return;
    }
    if (problem) {
      await repo.finish(runId, 'failed', problem);
      return;
    }
    await repo.patchMaterialization(runId, { refreshMs: Date.now() - started });
  }

  const all: StressAttempt[][] = queries.map(() => []);
  let stopped = false;
  let spent = 0;
  let overBudget = false;
  let tag = Date.now();
  outer: for (const [i, q] of queries.entries()) {
    if (materialization) {
      try {
        const plan = await read(`EXPLAIN EXTENDED ${q.sql(tag++)}`);
        await repo.saveMatched(runId, i, matchedName(plan.rows.flat().join('\n'), materialization.names));
      } catch (err) {
        console.warn(`EXPLAIN for try ${runId}: ${(err as Error).message.slice(0, 200)}`);
      }
    }
    for (let r = 0; r < settings.repeats; r++) {
      if ((await repo.status(runId)) !== 'running') {
        stopped = true;
        break outer;
      }
      const start = Date.now();
      try {
        const res = await read(q.sql(tag++));
        all[i].push({ statementId: res.statementId, wallMs: Date.now() - start });
      } catch (err) {
        all[i].push({ wallMs: Date.now() - start, error: (err as Error).message.slice(0, 500) });
      }
      await repo.saveAttempts(runId, i, all[i]);
      spent += all[i][all[i].length - 1].wallMs;
      if (budgetLeftMs != null && spent >= budgetLeftMs) {
        overBudget = stopped = true;
        break outer;
      }
    }
  }

  const ids = all.flat().flatMap((a) => (a.statementId ? [a.statementId] : []));
  const metrics = new Map<string, Omit<StressAttempt, 'wallMs'>>();
  const deadline = Date.now() + METRICS_WAIT_MS;
  try {
    while (metrics.size < ids.length && Date.now() < deadline) {
      for (const [k, v] of await uc.queryMetrics(ids.filter((id) => !metrics.has(id)))) metrics.set(k, v);
      if (metrics.size < ids.length) await sleep(3000);
    }
  } catch (err) {
    console.warn(`Query History for stress run ${runId}: ${(err as Error).message.slice(0, 200)}`);
  }
  for (const [i, attempts] of all.entries()) {
    const merged = attempts.map((a) => ({ ...a, ...(a.statementId ? metrics.get(a.statementId) : {}) }));
    await repo.saveAttempts(runId, i, merged);
  }
  await repo.finish(
    runId,
    stopped ? 'stopped' : 'finished',
    overBudget ? 'The monthly budget was reached.' : undefined
  );
}

const background = (repo: ReturnType<typeof stressRepo>, runId: string, job: Promise<void>) =>
  void job.catch(async (err: unknown) => {
    console.error(`Stress run ${runId} failed`, err);
    await repo.finish(runId, 'failed', (err as Error).message.slice(0, 1000)).catch(() => undefined);
  });

export function registerOptimizeRoutes(
  app: Application,
  db: Db,
  runFor: (req: Request) => RunDeps,
  ucFor: (req: Request) => UcDeps
) {
  const projects = projectRepo(db);
  const designs = designerRepo(db);
  const repo = stressRepo(db);

  async function costView(projectId: string, canEdit: boolean): Promise<CostView> {
    const runs = await repo.history(projectId);
    const byId = new Map(runs.map((r) => [r.id, r]));
    const costs = runs.map((r) => costOf(r, r.materialization ? byId.get(r.materialization.baseRun) : null));
    return {
      budgetMs: await repo.budget(projectId),
      usedMs: usedThisMonth(costs),
      monthStart: monthStart(new Date()).toISOString(),
      canEdit,
      runs: costs,
    };
  }

  /** Refuses a run that would pass the budget; returns the time left for the run to stop at. */
  async function budgetFor(projectId: string, statements: number) {
    const cost = await costView(projectId, false);
    const done = cost.runs.filter((r) => r.statements);
    const avgMs = done.length ? done.reduce((n, r) => n + r.execMs, 0) / done.reduce((n, r) => n + r.statements, 0) : 0;
    const problem = budgetCheck(cost.budgetMs, cost.usedMs, statements, avgMs);
    if (problem) throw new HttpError(409, problem);
    return cost.budgetMs === null ? null : cost.budgetMs - cost.usedMs;
  }

  async function context(req: Request) {
    const actor = actorOf(req);
    const project = await projects.get(actor, idParam.parse(req.params).id);
    const draft = (await designs.view(project.id)).draft;
    const view = draft ? validateMetricView(draft.yaml).view : undefined;
    const sandbox = sandboxSchema();
    const sandboxView = draft && sandbox ? sandboxViewName(sandbox, draft.name, project.id) : null;
    const matView = draft && sandbox ? sandboxViewName(sandbox, `${draft.name}_mat`, project.id) : null;
    return { actor, project, draft, view, sandboxView, matView };
  }

  app.get(
    '/api/projects/:id/optimize',
    handle(async (req): Promise<OptimizeView> => {
      const { project, draft, view, sandboxView } = await context(req);
      const latest = await repo.latest(project.id);
      const base = latest?.status === 'finished' && latest.version === draft?.version ? latest : null;
      return {
        draft: draft ? { version: draft.version, name: draft.name, status: draft.status } : null,
        workload: view && draft ? buildWorkload(view, draft.tests) : [],
        view: view
          ? { dimensions: view.dimensions.map((d) => d.name), measures: view.measures.map((m) => m.name) }
          : null,
        setup: draft && sandboxView ? { sandboxView, statements: [createStatement(sandboxView, draft.yaml)] } : null,
        limits: { maxQueries: MAX_QUERIES, maxRepeats: MAX_REPEATS, timeoutSeconds: TIMEOUT_SECONDS },
        latest,
        suggestion: base && view ? suggestMaterializations(view, base.id, base.queries) : null,
        latestTry: await repo.latest(project.id, true),
        practices: view ? bestPractices(view) : [],
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
      const budgetLeftMs = await budgetFor(project.id, queries.length * body.settings.repeats);
      const runId = await repo.start(
        actor,
        project.id,
        draft.version,
        sandboxView,
        body.settings,
        queries.map((q) => ({ query: q.query, sql: q.sql(0) }))
      );
      // The run outlives the request; it keeps the user's identity for every statement.
      background(
        repo,
        runId,
        execute({
          repo,
          runId,
          ctx: { actor, projectId: project.id },
          setup,
          queries,
          settings: body.settings,
          run: runFor(req),
          uc: ucFor(req),
          budgetLeftMs,
        })
      );
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

  /** The suggestion of the latest finished base run, limited to the views the user picked. */
  async function tryPlan(req: Request, schedule: (typeof SCHEDULES)[number], names: string[]) {
    const c = await context(req);
    if (!c.draft || !c.view || !c.matView) throw new HttpError(409, 'The design or the sandbox is not ready.');
    if (c.draft.status !== 'validated') throw new HttpError(409, 'Validate the design first.');
    const base = await repo.latest(c.project.id);
    if (base?.status !== 'finished' || base.version !== c.draft.version)
      throw new HttpError(409, 'Run a stress test of this version first.');
    const suggestion = suggestMaterializations(c.view, base.id, base.queries);
    const views = suggestion.views.filter((v) => names.includes(v.name));
    if (views.length !== new Set(names).size) throw new HttpError(409, 'The suggestion changed. Reload the page.');
    const yaml = withMaterialization(c.view, schedule, views);
    const plan: TryPlan = { matView: c.matView, yaml, statements: [createStatement(c.matView, yaml)] };
    return { ...c, base, views, plan };
  }

  app.get(
    '/api/projects/:id/optimize/tries/plan',
    handle(async (req): Promise<TryPlan> => {
      const { schedule, views } = planQuery.parse(req.query);
      return (await tryPlan(req, schedule, views.split(','))).plan;
    })
  );

  app.post(
    '/api/projects/:id/optimize/tries',
    handle(async (req) => {
      const body = trySchema.parse(req.body);
      const { actor, project, draft, base, views, plan } = await tryPlan(req, body.schedule, body.views);
      if (draft!.version !== body.version) throw new HttpError(409, 'The design changed. Reload the page.');
      if (body.statements.length !== plan.statements.length || body.statements.some((s, i) => s !== plan.statements[i]))
        throw new HttpError(409, 'The SQL changed since you reviewed it. Review it again.');
      const queries = base.queries.map((q) => {
        const query: WorkloadQuery = {
          label: q.label,
          dimensions: q.dimensions,
          measures: q.measures,
          origin: q.origin,
        };
        return { query, sql: (tag: number) => stressSql(plan.matView, query, tag) };
      });
      const materialization: MaterializationTry = { schedule: body.schedule, views, yaml: plan.yaml, baseRun: base.id };
      const budgetLeftMs = await budgetFor(project.id, queries.length * base.settings.repeats);
      const runId = await repo.start(
        actor,
        project.id,
        draft!.version,
        plan.matView,
        base.settings,
        queries.map((q) => ({ query: q.query, sql: q.sql(0) })),
        materialization
      );
      background(
        repo,
        runId,
        execute({
          repo,
          runId,
          ctx: { actor, projectId: project.id },
          setup: plan.statements,
          queries,
          settings: base.settings,
          run: runFor(req),
          uc: ucFor(req),
          materialization: { matView: plan.matView, names: views.map((v) => v.name) },
          budgetLeftMs,
        })
      );
      return { runId };
    })
  );

  /** Turning the materialization off stops the refreshes; then the view is dropped. */
  async function removal(req: Request) {
    const { id, runId } = runParam.parse(req.params);
    const actor = actorOf(req);
    const project = await projects.get(actor, id);
    const run = await repo.run(project.id, runId);
    if (!run.materialization) throw new HttpError(400, 'This run is not a materialization try.');
    // Every try of a sub-project uses the same view, so only the newest one may remove it.
    if ((await repo.latest(project.id, true))?.id !== run.id)
      throw new HttpError(409, 'A newer try replaced this one. Remove the newer try instead.');
    if (['running', 'refreshing', 'stopping'].includes(run.status)) throw new HttpError(409, 'Stop the try first.');
    const view = validateMetricView(run.materialization.yaml).view;
    if (!view) throw new HttpError(500, 'The stored YAML is not valid.');
    const plain = renderMetricView({ ...view, materialization: undefined });
    return {
      actor,
      project,
      run,
      statements: [createStatement(run.sandbox_view, plain), dropStatement(run.sandbox_view)],
    };
  }

  app.get(
    '/api/projects/:id/optimize/tries/:runId/remove',
    handle(async (req) => ({ statements: (await removal(req)).statements }))
  );

  app.post(
    '/api/projects/:id/optimize/tries/:runId/remove',
    handle(async (req) => {
      const { statements } = z.strictObject({ statements: z.array(z.string()).max(5) }).parse(req.body);
      const { actor, project, run, statements: expected } = await removal(req);
      if (statements.length !== expected.length || statements.some((s, i) => s !== expected[i]))
        throw new HttpError(409, 'The SQL changed since you reviewed it. Review it again.');
      for (const s of expected) await runStatement(s, { actor, projectId: project.id, approved: true }, runFor(req));
      await repo.patchMaterialization(run.id, { removed: true });
      return { removed: true, pipelineUrl: run.materialization?.pipelineUrl ?? null };
    })
  );

  app.get(
    '/api/projects/:id/optimize/cost',
    handle(async (req): Promise<CostView> => {
      const actor = actorOf(req);
      const project = await projects.get(actor, idParam.parse(req.params).id);
      return costView(project.id, project.createdBy === actor);
    })
  );

  app.post(
    '/api/projects/:id/optimize/budget',
    handle(async (req) => {
      const actor = actorOf(req);
      const project = await projects.get(actor, idParam.parse(req.params).id);
      if (project.createdBy !== actor) throw new HttpError(403, 'Only the owner of the sub-project sets its budget.');
      const { minutes } = z.strictObject({ minutes: z.number().positive().max(100_000).nullable() }).parse(req.body);
      await repo.setBudget(project.id, minutes === null ? null : Math.round(minutes * 60_000));
      return costView(project.id, true);
    })
  );

  /** DBUs billed to the try pipelines, from system.billing.usage. Needs read access to it. */
  app.post(
    '/api/projects/:id/optimize/cost/dbus',
    handle(async (req): Promise<BilledDbus> => {
      const actor = actorOf(req);
      const project = await projects.get(actor, idParam.parse(req.params).id);
      const ids = [
        ...new Set((await costView(project.id, false)).runs.flatMap((r) => (r.pipelineId ? [r.pipelineId] : []))),
      ].filter((id) => /^[0-9a-f-]{36}$/.test(id));
      if (!ids.length) return { pipelines: [], error: null };
      try {
        const res = await runStatement(
          `SELECT usage_metadata.dlt_pipeline_id AS pipeline_id, SUM(usage_quantity) AS dbus
           FROM system.billing.usage
           WHERE usage_metadata.dlt_pipeline_id IN (${ids.map((id) => `'${id}'`).join(', ')})
           GROUP BY ALL`,
          { actor, projectId: project.id, approved: false },
          runFor(req)
        );
        return { pipelines: res.rows.map((r) => ({ pipelineId: r[0] ?? '', dbus: Number(r[1] ?? 0) })), error: null };
      } catch (err) {
        return {
          pipelines: [],
          error: `Billing data is not available to you: ${(err as Error).message.slice(0, 200)}. An account or workspace admin can read system.billing.usage.`,
        };
      }
    })
  );
}
