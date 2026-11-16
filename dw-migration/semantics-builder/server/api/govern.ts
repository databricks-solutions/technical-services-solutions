import type { Application, Request } from 'express';
import { z } from 'zod';
import type { LakebasePool } from '@databricks/appkit';
import { governRunSchema, governSchema, tagRunSchema, tagSchema } from '../../shared/govern';
import type { GovernView, TagsView, ViewTag } from '../../shared/govern';
import { validateMetricView } from '../../shared/metricView';
import { governStatement, tagStatement } from '../designer/govern';
import { quoteId, quoteName, sqlString } from '../readiness/profile';
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

  /** Tags of the view and of its fields, read as the user from the catalog's information schema. */
  async function readTags(req: Request): Promise<{ actor: string; projectId: string; view: TagsView }> {
    const { actor, project, view: g } = await read(req);
    const base: TagsView = { target: g.target, youOwn: g.youOwn, columns: [], tags: [], problem: g.problem };
    if (g.problem || !g.target) return { actor, projectId: project.id, view: base };
    const [catalog, schema, table] = g.target.split('.');
    const where = `WHERE table_schema = ${sqlString(schema)} AND table_name = ${sqlString(table)}`;
    const tagsWhere = `WHERE schema_name = ${sqlString(schema)} AND table_name = ${sqlString(table)}`;
    const info = `${quoteId(catalog)}.information_schema`;
    const ctx = { actor, projectId: project.id, approved: false };
    const [cols, viewTags, colTags] = await Promise.all([
      runStatement(`SELECT column_name FROM ${info}.columns ${where} ORDER BY ordinal_position`, ctx, runFor(req)),
      runStatement(`SELECT tag_name, tag_value FROM ${info}.table_tags ${tagsWhere}`, ctx, runFor(req)),
      runStatement(`SELECT column_name, tag_name, tag_value FROM ${info}.column_tags ${tagsWhere}`, ctx, runFor(req)),
    ]);
    const tags: ViewTag[] = [
      ...viewTags.rows.map(([name, value]) => ({ column: null, name: name ?? '', value: value ?? '' })),
      ...colTags.rows.map(([column, name, value]) => ({ column, name: name ?? '', value: value ?? '' })),
    ];
    return {
      actor,
      projectId: project.id,
      view: { ...base, columns: cols.rows.map((r) => r[0] ?? '').filter(Boolean), tags },
    };
  }

  const planTag = (view: TagsView, tag: { column: string | null; name: string; value: string | null }) => {
    if (view.problem || !view.target) throw new HttpError(409, view.problem ?? 'Nothing to tag.');
    if (!view.youOwn) throw new HttpError(403, 'Only the owner of the view can change its tags.');
    if (tag.column && !view.columns.includes(tag.column))
      throw new HttpError(400, `The view has no field named ${tag.column}.`);
    if (tag.value !== null && !tag.value) throw new HttpError(400, 'Give the tag a value.');
    return tagStatement(view.target, tag);
  };

  app.get(
    '/api/projects/:id/governance/tags',
    handle(async (req) => (await readTags(req)).view)
  );

  app.post(
    '/api/projects/:id/governance/tags/preview',
    handle(async (req) => ({ statement: planTag((await readTags(req)).view, tagSchema.parse(req.body)) }))
  );

  app.post(
    '/api/projects/:id/governance/tags',
    handle(async (req) => {
      const { statement, ...tag } = tagRunSchema.parse(req.body);
      const { actor, projectId, view } = await readTags(req);
      if (planTag(view, tag) !== statement)
        throw new HttpError(409, 'The statement changed since you reviewed it. Review it again.');
      await runStatement(statement, { actor, projectId, approved: true }, runFor(req));
      return (await readTags(req)).view;
    })
  );

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
