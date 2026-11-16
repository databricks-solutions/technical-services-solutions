import type { Application, Request } from 'express';
import { z } from 'zod';
import type { LakebasePool } from '@databricks/appkit';
import type { BiCheck } from '../../shared/bi';
import { validateMetricView } from '../../shared/metricView';
import type { MetricView } from '../../shared/metricView';
import { quoteId, quoteName } from '../readiness/profile';
import { runStatement } from '../sql/runner';
import type { RunDeps } from '../sql/runner';
import { designerRepo } from './designer';
import { actorOf, handle, HttpError } from './http';
import { projectRepo } from './projects';

type Db = Pick<LakebasePool, 'query' | 'connect'>;
const idParam = z.object({ id: z.uuid() });
const CHECK_ROWS = 100;

/** The query a BI tool sends with Custom SQL or a Native query: a dimension, a measure with MEASURE(), GROUP BY. */
export function biQuery(target: string, view: MetricView): { sql: string; dimension: string; measure: string } | null {
  // A window measure needs its time dimension, so the check uses a plain measure and a plain dimension.
  const measure = view.measures.find((m) => !m.window && !/\bOVER\s*\(/i.test(m.expr)) ?? view.measures[0];
  const dimension = view.dimensions[0];
  if (!measure || !dimension) return null;
  const d = quoteId(dimension.name);
  return {
    sql: `SELECT ${d}, MEASURE(${quoteId(measure.name)}) AS ${quoteId(measure.name)}\nFROM ${quoteName(target)}\nGROUP BY ${d}`,
    dimension: dimension.name,
    measure: measure.name,
  };
}

/**
 * A connection check for BI tools on the promoted view: the query shape that Power BI and Tableau send, run as the
 * user. GET shows it; POST runs it and keeps nothing (the result has the row count, not the values).
 */
export function registerBiRoutes(app: Application, db: Db, runFor: (req: Request) => RunDeps) {
  const projects = projectRepo(db);
  const designs = designerRepo(db);

  async function plan(req: Request) {
    const actor = actorOf(req);
    const project = await projects.get(actor, idParam.parse(req.params).id);
    const { rows } = await db.query<{ version: number; target: string }>(
      `SELECT pr.version, pr.target FROM gsb.promotion pr JOIN gsb.project p ON p.id = pr.project_id
       WHERE pr.project_id = $1 AND pr.status = 'succeeded' AND pr.target = p.promotion_target
       ORDER BY pr.created_at DESC LIMIT 1`,
      [project.id]
    );
    const p = rows[0];
    const empty: BiCheck = { target: null, version: null, sql: null, dimension: null, measure: null, result: null };
    if (!p) return { actor, project, check: empty };
    const view = validateMetricView((await designs.view(project.id, p.version)).draft!.yaml).view;
    if (!view) throw new HttpError(409, `Version ${p.version} does not parse.`);
    const q = biQuery(p.target, view);
    return { actor, project, check: { ...empty, target: p.target, version: p.version, ...(q ?? {}) } };
  }

  app.get(
    '/api/projects/:id/bi',
    handle(async (req) => (await plan(req)).check)
  );

  app.post(
    '/api/projects/:id/bi',
    handle(async (req): Promise<BiCheck> => {
      const { actor, project, check } = await plan(req);
      if (!check.sql) throw new HttpError(409, 'Promote a version with a dimension and a measure first.');
      try {
        const out = await runStatement(
          `${check.sql}\nLIMIT ${CHECK_ROWS}`,
          { actor, projectId: project.id, approved: false },
          runFor(req)
        );
        const rows = out.rows.length;
        return {
          ...check,
          result: rows
            ? {
                status: 'passed',
                rows,
                detail: `The query ran as you and returned ${rows} row${rows === 1 ? '' : 's'}.`,
              }
            : {
                status: 'failed',
                rows,
                detail: 'The query ran but returned no rows. Check the source data and filters.',
              },
        };
      } catch (err) {
        return { ...check, result: { status: 'failed', rows: 0, detail: (err as Error).message.slice(0, 500) } };
      }
    })
  );
}
