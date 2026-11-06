import type { Application, Request } from 'express';
import { z } from 'zod';
import type { LakebasePool } from '@databricks/appkit';
import { baselineSchema } from '../../shared/drift';
import type { DriftCheck, DriftFinding, DriftSnapshot, DriftView } from '../../shared/drift';
import { validateMetricView } from '../../shared/metricView';
import type { MetricView } from '../../shared/metricView';
import { tablesOf } from '../designer/import';
import { driftFindings } from '../drift/findings';
import { quoteId, quoteName } from '../readiness/profile';
import type { TableProfile } from '../readiness/profile';
import { runStatement } from '../sql/runner';
import type { RunDeps } from '../sql/runner';
import { profileFromTable } from '../uc/metadata';
import type { UcDeps } from '../uc/metadata';
import { actorOf, handle, HttpError } from './http';
import { projectRepo } from './projects';

type Db = Pick<LakebasePool, 'query' | 'connect'>;
const idParam = z.object({ id: z.uuid() });
const MAX_TOTALS = 20;
const notFound = (err: unknown) => /does not exist|not found|TABLE_OR_VIEW_NOT_FOUND|404/i.test((err as Error).message);

interface Baseline {
  at: string;
  by: string;
  values: Record<string, number | null>;
}

/** One row of totals for the plain (non-window) measures of the view. Reads only, as the user. */
export function totalsQuery(target: string, view: MetricView): { sql: string; names: string[] } | null {
  const names = view.measures
    .filter((m) => !m.window)
    .map((m) => m.name)
    .slice(0, MAX_TOTALS);
  if (!names.length) return null;
  return {
    sql: `SELECT ${names.map((n, i) => `MEASURE(${quoteId(n)}) AS m${i}`).join(', ')} FROM ${quoteName(target)}`,
    names,
  };
}

/** Drift checks of the promoted view, on demand and as the user. Findings and snapshots go to Lakebase. */
export function registerDriftRoutes(
  app: Application,
  db: Db,
  runFor: (req: Request) => RunDeps,
  ucFor: (req: Request) => UcDeps
) {
  const projects = projectRepo(db);

  async function context(req: Request) {
    const actor = actorOf(req);
    const project = await projects.get(actor, idParam.parse(req.params).id);
    const { rows } = await db.query<{ target: string | null; baseline: Baseline | null; yaml: string | null }>(
      `SELECT p.promotion_target AS target, p.data_baseline AS baseline,
         (SELECT yaml FROM gsb.promotion pr WHERE pr.project_id = p.id AND pr.status = 'succeeded'
            AND pr.target = p.promotion_target ORDER BY created_at DESC LIMIT 1) AS yaml
       FROM gsb.project p WHERE p.id = $1`,
      [project.id]
    );
    const r = rows[0];
    return { actor, project, target: r?.target ?? null, baseline: r?.baseline ?? null, promotedYaml: r?.yaml ?? null };
  }

  async function totals(req: Request, ctx: Awaited<ReturnType<typeof context>>, yaml: string) {
    const view = validateMetricView(yaml).view;
    const q = view && ctx.target ? totalsQuery(ctx.target, view) : null;
    if (!q) return {};
    const res = await runStatement(
      q.sql,
      { actor: ctx.actor, projectId: ctx.project.id, approved: false },
      runFor(req)
    );
    const row = res.rows[0] ?? [];
    return Object.fromEntries(
      q.names.map((n, i) => {
        const v = row[i];
        const num = v === null || v === undefined ? null : Number(v);
        return [n, num !== null && Number.isFinite(num) ? num : null];
      })
    );
  }

  async function view(req: Request): Promise<DriftView> {
    const ctx = await context(req);
    const problem = !ctx.target
      ? 'Set the Unity Catalog view and promote it first.'
      : !ctx.promotedYaml
        ? `Promote a version to ${ctx.target} first.`
        : null;
    const { rows } = await db.query<{
      id: string;
      target: string;
      findings: DriftFinding[];
      created_by: string;
      created_at: Date;
    }>(
      `SELECT id, target, findings, created_by, created_at FROM gsb.drift_check
       WHERE project_id = $1 ORDER BY created_at DESC LIMIT 30`,
      [ctx.project.id]
    );
    const last: DriftCheck | null = rows[0]
      ? {
          id: rows[0].id,
          target: rows[0].target,
          findings: rows[0].findings,
          createdBy: rows[0].created_by,
          createdAt: rows[0].created_at.toISOString(),
        }
      : null;
    return {
      target: ctx.target,
      problem,
      last,
      history: rows.map((r) => ({
        id: r.id,
        createdAt: r.created_at.toISOString(),
        errors: r.findings.filter((f) => f.severity === 'error').length,
        warnings: r.findings.filter((f) => f.severity === 'warning').length,
      })),
      baseline: ctx.baseline
        ? { at: ctx.baseline.at, by: ctx.baseline.by, measures: Object.keys(ctx.baseline.values).length }
        : null,
    };
  }

  app.get('/api/projects/:id/drift', handle(view));

  app.post(
    '/api/projects/:id/drift/check',
    handle(async (req) => {
      const ctx = await context(req);
      if (!ctx.target || !ctx.promotedYaml) throw new HttpError(409, (await view(req)).problem ?? 'Promote first.');
      const uc = ucFor(req);
      const run = runFor(req);
      const as = { actor: ctx.actor, projectId: ctx.project.id, approved: false };

      let ucYaml: string | null = null;
      let owner: string | null = null;
      try {
        const t = await uc.table(ctx.target);
        ucYaml = t.view_definition ?? '';
        owner = t.owner ?? null;
      } catch (err) {
        if (!notFound(err))
          throw new HttpError(502, `Cannot read ${ctx.target}: ${(err as Error).message.slice(0, 300)}`);
      }
      const yaml = ucYaml ?? ctx.promotedYaml;
      const parsed = validateMetricView(yaml).view;
      const restricted: string[] = [];
      const sources = await Promise.all(
        (parsed ? tablesOf(parsed) : []).map(
          async (fullName): Promise<{ fullName: string; profile?: TableProfile; error?: string }> => {
            try {
              const t = await uc.table(fullName);
              if (t.row_filter || t.columns?.some((c) => c.mask)) restricted.push(fullName);
              return { fullName, profile: profileFromTable(fullName, t) };
            } catch (err) {
              return { fullName, error: (err as Error).message.slice(0, 300) };
            }
          }
        )
      );

      let grants: string[] = [];
      let refreshStatus: string | null = null;
      let current: Record<string, number | null> | null = null;
      if (ucYaml !== null) {
        const g = await runStatement(`SHOW GRANTS ON VIEW ${quoteName(ctx.target)}`, as, run);
        const p = g.columns.indexOf('Principal');
        const a = g.columns.indexOf('ActionType');
        grants = g.rows.map((r) => `${r[p] ?? ''}:${r[a] ?? ''}`);
        if (parsed?.materialization !== undefined) {
          const d = await runStatement(`DESCRIBE EXTENDED ${quoteName(ctx.target)}`, as, run);
          refreshStatus = d.rows.find((r) => r[0]?.trim() === 'Latest Refresh Status')?.[1]?.trim() ?? null;
        }
        if (ctx.baseline) current = await totals(req, ctx, yaml).catch(() => ({}));
      }

      const { rows: prev } = await db.query<{ snapshot: DriftSnapshot }>(
        'SELECT snapshot FROM gsb.drift_check WHERE project_id = $1 ORDER BY created_at DESC LIMIT 1',
        [ctx.project.id]
      );
      const { findings, snapshot } = driftFindings({
        target: ctx.target,
        promotedYaml: ctx.promotedYaml,
        ucYaml,
        sources,
        owner,
        grants,
        restricted,
        materialized: parsed?.materialization !== undefined,
        refreshStatus,
        totals: current,
        baseline: ctx.baseline?.values ?? null,
        previous: prev[0]?.snapshot ?? null,
      });
      await db.query(
        `INSERT INTO gsb.drift_check (project_id, target, findings, snapshot, created_by) VALUES ($1, $2, $3, $4, $5)`,
        [ctx.project.id, ctx.target, JSON.stringify(findings), JSON.stringify(snapshot), ctx.actor]
      );
      return view(req);
    })
  );

  /** Opt in to data drift: stores the measure totals of the view now. Opt out deletes them. */
  app.post(
    '/api/projects/:id/drift/baseline',
    handle(async (req) => {
      const { enable } = baselineSchema.parse(req.body);
      const ctx = await context(req);
      if (enable && (!ctx.target || !ctx.promotedYaml)) throw new HttpError(409, 'Promote the view first.');
      const baseline: Baseline | null = enable
        ? { at: new Date().toISOString(), by: ctx.actor, values: await totals(req, ctx, ctx.promotedYaml!) }
        : null;
      await db.query(
        `WITH u AS (UPDATE gsb.project SET data_baseline = $2 WHERE id = $1 RETURNING id)
         INSERT INTO gsb.audit_log (actor, action, project_id, target, outcome)
         SELECT $3, $4, id, $5, 'succeeded' FROM u`,
        [
          ctx.project.id,
          baseline ? JSON.stringify(baseline) : null,
          ctx.actor,
          enable ? 'set_data_baseline' : 'clear_data_baseline',
          ctx.target,
        ]
      );
      return view(req);
    })
  );
}
