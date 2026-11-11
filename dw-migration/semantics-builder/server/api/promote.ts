import type { Application, Request } from 'express';
import { z } from 'zod';
import type { LakebasePool } from '@databricks/appkit';
import { promoteSchema, targetSchema } from '../../shared/promote';
import type { Impact, Promotion, PromotionView } from '../../shared/promote';
import { validateMetricView } from '../../shared/metricView';
import { fieldChanges, IMPACT_DAYS, impactQuery, toConsumers, watched } from '../designer/impact';
import { createStatement, sandboxSchema } from '../designer/validate';
import { checkTarget, sameYaml } from '../designer/promote';
import { runStatement } from '../sql/runner';
import type { RunDeps } from '../sql/runner';
import type { UcDeps } from '../uc/metadata';
import { actorOf, handle, HttpError } from './http';
import { designerRepo } from './designer';
import { projectRepo } from './projects';

type Db = Pick<LakebasePool, 'query' | 'connect'>;
const idParam = z.object({ id: z.uuid() });

interface PromotionRow {
  id: string;
  version: number;
  target: string;
  status: Promotion['status'];
  error: string | null;
  created_by: string;
  created_at: Date;
}

const notFound = (err: unknown) => /does not exist|not found|TABLE_OR_VIEW_NOT_FOUND|404/i.test((err as Error).message);

export function registerPromoteRoutes(
  app: Application,
  db: Db,
  runFor: (req: Request) => RunDeps,
  ucFor: (req: Request) => UcDeps
) {
  const projects = projectRepo(db);
  const designs = designerRepo(db);

  async function context(req: Request) {
    const actor = actorOf(req);
    const project = await projects.get(actor, idParam.parse(req.params).id);
    if (!project.parentId) throw new HttpError(400, 'Promote from a sub-project.');
    const { rows } = await db.query<{ promotion_target: string | null }>(
      'SELECT promotion_target FROM gsb.project WHERE id = $1',
      [project.id]
    );
    return { actor, project, target: rows[0]?.promotion_target ?? null };
  }

  /** The statement for the latest version, and whether the view in UC was changed outside the app. */
  async function build(req: Request): Promise<PromotionView> {
    const { project, target } = await context(req);
    const { rows } = await db.query<PromotionRow>(
      `SELECT id, version, target, status, error, created_by, created_at FROM gsb.promotion
       WHERE project_id = $1 ORDER BY created_at DESC LIMIT 50`,
      [project.id]
    );
    const promotions = rows.map((r) => ({
      id: r.id,
      version: r.version,
      target: r.target,
      status: r.status,
      error: r.error,
      createdBy: r.created_by,
      createdAt: r.created_at.toISOString(),
    }));
    const draft = (await designs.view(project.id)).draft;
    const base = { target, promotions, plan: null };
    if (!target) return { ...base, problem: 'Set the Unity Catalog view to promote to.' };
    if (!draft) return { ...base, problem: 'Design the metric view first.' };
    if (draft.status !== 'validated')
      return { ...base, problem: `Validate version ${draft.version} before you promote it.` };

    let ucYaml: string | null = null;
    try {
      ucYaml = (await ucFor(req).table(target)).view_definition ?? '';
    } catch (err) {
      if (!notFound(err)) return { ...base, problem: `Cannot read ${target}: ${(err as Error).message.slice(0, 300)}` };
    }
    const { rows: yamls } = await db.query<{ yaml: string }>(
      'SELECT DISTINCT yaml FROM gsb.metric_view_draft WHERE project_id = $1',
      [project.id]
    );
    return {
      ...base,
      problem: null,
      plan: {
        version: draft.version,
        statement: createStatement(target, draft.yaml),
        exists: ucYaml !== null,
        changedOutside: ucYaml !== null && !yamls.some((y) => sameYaml(y.yaml, ucYaml)),
        ucYaml,
      },
    };
  }

  app.get('/api/projects/:id/promotion', handle(build));

  /** What the latest version changes in the view in Unity Catalog, and who reads that view, from lineage. */
  app.get(
    '/api/projects/:id/promotion/impact',
    handle(async (req): Promise<Impact> => {
      const { actor, project, target } = await context(req);
      const base = { changes: null, consumers: null, days: IMPACT_DAYS };
      const draft = (await designs.view(project.id)).draft;
      if (!target || !draft) return { ...base, error: 'Set the target and design the view first.' };
      let ucYaml: string;
      try {
        ucYaml = (await ucFor(req).table(target)).view_definition ?? '';
      } catch (err) {
        if (notFound(err)) return { ...base, consumers: [], error: null };
        return { ...base, error: `Cannot read ${target}: ${(err as Error).message.slice(0, 300)}` };
      }
      const before = validateMetricView(ucYaml).view;
      const after = validateMetricView(draft.yaml).view;
      const changes = before && after ? fieldChanges(before, after) : null;
      const fields = watched(changes);
      try {
        const result = await runStatement(
          impactQuery(target, fields),
          { actor, projectId: project.id, approved: false },
          runFor(req)
        );
        return { ...base, changes, consumers: toConsumers(result.rows, fields), error: null };
      } catch (err) {
        return {
          ...base,
          changes,
          error: `Cannot read lineage. You need SELECT on system.access.table_lineage and system.access.column_lineage. ${(err as Error).message.slice(0, 300)}`,
        };
      }
    })
  );

  app.post(
    '/api/projects/:id/promotion/target',
    handle(async (req) => {
      const { fullName } = targetSchema.parse(req.body);
      const { actor, project } = await context(req);
      const problem = checkTarget(fullName, sandboxSchema());
      if (problem) throw new HttpError(400, problem);
      await db.query(
        `WITH u AS (UPDATE gsb.project SET promotion_target = $2 WHERE id = $1 RETURNING id)
         INSERT INTO gsb.audit_log (actor, action, project_id, target, outcome)
         SELECT $3, 'set_promotion_target', id, $2, 'succeeded' FROM u`,
        [project.id, fullName, actor]
      );
      return build(req);
    })
  );

  /** Runs the reviewed CREATE OR REPLACE as the user. A view changed outside the app needs overwrite: true. */
  app.post(
    '/api/projects/:id/promotion',
    handle(async (req) => {
      const body = promoteSchema.parse(req.body);
      const { actor, project, target } = await context(req);
      const view = await build(req);
      const plan = view.plan;
      if (!plan || !target) throw new HttpError(409, view.problem ?? 'Nothing to promote.');
      if (plan.version !== body.version || plan.statement !== body.statement)
        throw new HttpError(409, 'The design changed since you reviewed it. Review it again.');
      if (plan.changedOutside && !body.overwrite)
        throw new HttpError(409, `${target} was changed outside the app. Review the difference, then confirm.`);
      const draft = (await designs.view(project.id)).draft!;
      const { rows } = await db.query<{ id: string }>(
        `INSERT INTO gsb.promotion (project_id, version, target, yaml, created_by) VALUES ($1, $2, $3, $4, $5)
         RETURNING id`,
        [project.id, plan.version, target, draft.yaml, actor]
      );
      const id = rows[0].id;
      try {
        await runStatement(plan.statement, { actor, projectId: project.id, approved: true }, runFor(req));
        await db.query(`UPDATE gsb.promotion SET status = 'succeeded', finished_at = now() WHERE id = $1`, [id]);
      } catch (err) {
        await db.query(`UPDATE gsb.promotion SET status = 'failed', error = $2, finished_at = now() WHERE id = $1`, [
          id,
          (err as Error).message.slice(0, 1000),
        ]);
      }
      return build(req);
    })
  );
}
