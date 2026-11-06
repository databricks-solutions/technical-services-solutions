import type { Application, Request } from 'express';
import { z } from 'zod';
import type { LakebasePool } from '@databricks/appkit';
import { IMPORTED_SUMMARY, UC_TABLE_NAME } from '../../shared/brief';
import { importDesign } from '../designer/import';
import type { UcDeps } from '../uc/metadata';
import { actorOf, handle, HttpError } from './http';
import { designerRepo } from './designer';
import { projectRepo } from './projects';
import { MAX_SOURCES } from './readiness';

type Db = Pick<LakebasePool, 'query' | 'connect'>;
const name = z.string().trim().min(1).max(200);
const importBody = z
  .object({
    view: z.string().regex(UC_TABLE_NAME),
    /** An existing project, or null to create one named projectName. */
    parentId: z.uuid().nullable(),
    projectName: name.optional(),
    subProject: name,
  })
  .refine((b) => b.parentId !== null || !!b.projectName, { message: 'Name the new project.' });

/**
 * Imports a metric view made outside the app, read as the user: a sub-project with its sources, a brief
 * draft to confirm, design version 1 with the YAML as it is in UC, and the view as the promotion target.
 */
export function registerImportRoutes(app: Application, db: Db, ucFor: (req: Request) => UcDeps) {
  const projects = projectRepo(db);
  const designs = designerRepo(db);

  app.post(
    '/api/import',
    handle(async (req) => {
      const actor = actorOf(req);
      const body = importBody.parse(req.body);
      const table = await ucFor(req).table(body.view);
      if (table.table_type !== 'METRIC_VIEW') throw new HttpError(400, `${body.view} is not a metric view.`);
      let imported: ReturnType<typeof importDesign>;
      try {
        imported = importDesign(table.full_name ?? body.view, table.view_definition ?? '');
      } catch (err) {
        throw new HttpError(400, (err as Error).message);
      }
      if (imported.sources.length > MAX_SOURCES)
        throw new HttpError(400, `The view uses more than ${MAX_SOURCES} tables, the limit of a sub-project.`);

      const parent = body.parentId
        ? await projects.get(actor, body.parentId)
        : await projects.create(actor, { name: body.projectName! });
      if (parent.parentId) throw new HttpError(400, 'Pick a project, not a sub-project.');
      const sub = await projects.create(actor, { name: body.subProject }, parent.id);

      await db.query(
        `INSERT INTO gsb.source (project_id, full_name, added_by) SELECT $1, unnest($2::text[]), $3
         ON CONFLICT (project_id, full_name) DO NOTHING`,
        [sub.id, imported.sources, actor]
      );
      await projects.addDraft(
        actor,
        sub.id,
        { brief: imported.brief, summary: IMPORTED_SUMMARY },
        { imported: body.view }
      );
      await designs.add(actor, sub.id, {
        name: imported.name,
        yaml: imported.yaml,
        explanations: { summary: `Imported from ${body.view}.`, measures: {}, dimensions: {} },
        tests: imported.tests,
        issues: imported.issues,
        origin: 'imported',
      });
      await db.query(
        `WITH u AS (UPDATE gsb.project SET promotion_target = $2 WHERE id = $1 RETURNING id)
         INSERT INTO gsb.audit_log (actor, action, project_id, target, outcome)
         SELECT $3, 'import_metric_view', id, $2, 'succeeded' FROM u`,
        [sub.id, table.full_name ?? body.view, actor]
      );
      return { parentId: parent.id, projectId: sub.id };
    })
  );
}
