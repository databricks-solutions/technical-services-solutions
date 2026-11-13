import type { Application, Request } from 'express';
import { z } from 'zod';
import type { LakebasePool } from '@databricks/appkit';
import { governRunSchema, governSchema } from '../../shared/govern';
import type { GovernView } from '../../shared/govern';
import { validateMetricView } from '../../shared/metricView';
import { governStatement } from '../designer/govern';
import { quoteName } from '../readiness/profile';
import { runStatement } from '../sql/runner';
import type { RunDeps } from '../sql/runner';
import type { UcDeps } from '../uc/metadata';
import { actorOf, handle, HttpError } from './http';
import { projectRepo } from './projects';

type Db = Pick<LakebasePool, 'query' | 'connect'>;
const idParam = z.object({ id: z.uuid() });

/**
 * Owner and read grants of the promoted view, as SQL run as the user (the grants API needs the
 * unity-catalog scope, which apps cannot have). Every change is one reviewed statement on that view only.
 */
export function registerGovernRoutes(
  app: Application,
  db: Db,
  runFor: (req: Request) => RunDeps,
  ucFor: (req: Request) => UcDeps
) {
  const projects = projectRepo(db);

  async function read(req: Request) {
    const actor = actorOf(req);
    const project = await projects.get(actor, idParam.parse(req.params).id);
    const { rows } = await db.query<{ target: string | null; promoted: boolean }>(
      `SELECT promotion_target AS target, EXISTS (
         SELECT 1 FROM gsb.promotion WHERE project_id = $1 AND status = 'succeeded' AND target = p.promotion_target
       ) AS promoted
       FROM gsb.project p WHERE id = $1`,
      [project.id]
    );
    const target = rows[0]?.target ?? null;
    const base: GovernView = { target, owner: null, youOwn: false, materialized: false, grants: [], problem: null };
    if (!target)
      return { actor, project, view: { ...base, problem: 'Set the Unity Catalog view and promote it first.' } };
    if (!rows[0]?.promoted)
      return { actor, project, view: { ...base, problem: `Promote a version to ${target} first.` } };
    const uc = ucFor(req);
    const [table, me] = await Promise.all([uc.table(target), uc.me()]);
    const owner = table.owner ?? null;
    const grants = await runStatement(
      `SHOW GRANTS ON VIEW ${quoteName(target)}`,
      { actor, projectId: project.id, approved: false },
      runFor(req)
    );
    const i = { p: grants.columns.indexOf('Principal'), a: grants.columns.indexOf('ActionType') };
    const view: GovernView = {
      ...base,
      owner,
      youOwn: !!owner && (owner === me.userName || me.groups.includes(owner)),
      materialized: validateMetricView(table.view_definition ?? '').view?.materialization !== undefined,
      grants: grants.rows.map((r) => ({ principal: r[i.p] ?? '', privilege: r[i.a] ?? '' })).filter((g) => g.principal),
    };
    return { actor, project, view };
  }

  const plan = (view: GovernView, action: 'owner' | 'grant' | 'revoke', principal: string) => {
    if (view.problem || !view.target) throw new HttpError(409, view.problem ?? 'Nothing to govern.');
    if (!view.youOwn)
      throw new HttpError(403, `Only the owner (${view.owner ?? 'unknown'}) can change access or the owner.`);
    if (action === 'owner' && view.materialized)
      throw new HttpError(
        409,
        'The view has a materialization, so its owner cannot change. Remove the materialization first.'
      );
    if (action === 'owner' && principal === view.owner) throw new HttpError(400, `${principal} already owns the view.`);
    return governStatement(action, view.target, principal);
  };

  app.get(
    '/api/projects/:id/governance',
    handle(async (req) => (await read(req)).view)
  );

  app.post(
    '/api/projects/:id/governance/preview',
    handle(async (req) => {
      const { action, principal } = governSchema.parse(req.body);
      return { statement: plan((await read(req)).view, action, principal) };
    })
  );

  app.post(
    '/api/projects/:id/governance',
    handle(async (req) => {
      const { action, principal, statement } = governRunSchema.parse(req.body);
      const { actor, project, view } = await read(req);
      if (plan(view, action, principal) !== statement)
        throw new HttpError(409, 'The statement changed since you reviewed it. Review it again.');
      await runStatement(statement, { actor, projectId: project.id, approved: true }, runFor(req));
      return (await read(req)).view;
    })
  );
}
