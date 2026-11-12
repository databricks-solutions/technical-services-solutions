import type { Application, Request } from 'express';
import { z } from 'zod';
import type { LakebasePool } from '@databricks/appkit';
import { IMPORTED_SUMMARY, UC_TABLE_NAME } from '../../shared/brief';
import { legacyBody } from '../../shared/legacy';
import { importDesign } from '../designer/import';
import { convertDbt } from '../legacy/dbt';
import { convertLookml } from '../legacy/lookml';
import { convertTabular } from '../legacy/tabular';
import type { LegacyResult } from '../legacy/common';
import { callTool } from '../llm/llm';
import type { LlmDeps } from '../llm/llm';
import { calcPrompt, calcRequest, safeExpression } from '../llm/prompts/legacyCalc';
import { convertTableau } from '../legacy/tableau';
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
    /** Views that this one replaces, from discover. Kept in the audit log. */
    replaces: z.array(z.string().regex(UC_TABLE_NAME)).max(50).optional(),
  })
  .refine((b) => b.parentId !== null || !!b.projectName, { message: 'Name the new project.' });

/**
 * Imports a metric view made outside the app, read as the user: a sub-project with its sources, a brief
 * draft to confirm, design version 1 with the YAML as it is in UC, and the view as the promotion target.
 */
const MAX_AI_MEASURES = 20;

export function registerImportRoutes(
  app: Application,
  db: Db,
  ucFor: (req: Request) => UcDeps,
  llmFor: (req: Request) => LlmDeps
) {
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
         INSERT INTO gsb.audit_log (actor, action, project_id, target, outcome, detail)
         SELECT $3, 'import_metric_view', id, $2, 'succeeded', $4 FROM u`,
        [sub.id, table.full_name ?? body.view, actor, body.replaces?.length ? { replaces: body.replaces } : null]
      );
      return { parentId: parent.id, projectId: sub.id };
    })
  );

  /**
   * A legacy semantic model (dbt MetricFlow first) to a draft metric view in a new sub-project of this project.
   * Without create, it returns the preview: the YAML, each field with its source and status, and the issues. The
   * file is data: it is parsed, never run, and its tables are only named, not read.
   */
  app.post(
    '/api/projects/:id/import/legacy',
    handle(async (req) => {
      const actor = actorOf(req);
      const body = legacyBody.parse(req.body);
      const parent = await projects.get(actor, z.object({ id: z.uuid() }).parse(req.params).id);
      if (parent.parentId) throw new HttpError(400, 'Import into a project, not a sub-project.');
      // .bim and .pbit are Tabular (Power BI, SSAS); .twb, .tds, .twbx and .tdsx are Tableau. LookML files end in
      // .lkml; several uploaded files arrive joined. Else the file is dbt YAML or JSON.
      const tabular = /\.(bim|pbit)$/i.test(body.fileName);
      const tableau = /\.(twbx?|tdsx?)$/i.test(body.fileName);
      const withAi = tabular || tableau;
      const lookml =
        !withAi && (/\.lkml$/i.test(body.fileName) || /^\s*(view|explore|include|connection)\s*:/m.test(body.content));
      const tool = tabular ? 'Power BI / Tabular' : tableau ? 'Tableau' : lookml ? 'LookML' : 'dbt MetricFlow';
      let result: LegacyResult;
      try {
        if (!withAi) result = (lookml ? convertLookml : convertDbt)(body.fileName, body.content, body.schema);
        else {
          const base64 = body.encoding === 'base64';
          // On create, the SQL that the user saw in the preview; on preview, the AI for each measure with no rule.
          let ai = new Map(Object.entries(body.ai ?? {}).flatMap(([k, v]) => (safeExpression(v) ? [[k, v]] : [])));
          const convert = tabular ? convertTabular : convertTableau;
          const first = convert(body.fileName, body.content, body.schema, base64, ai);
          if (!body.create && first.todo.length) {
            const llm = llmFor(req);
            const found = await Promise.all(
              first.todo.slice(0, MAX_AI_MEASURES).map(async (t) => {
                try {
                  const out = await callTool(
                    calcPrompt(tabular ? 'DAX' : 'Tableau'),
                    calcRequest(tabular ? 'DAX' : 'Tableau', t.dax, first.catalog.columns, first.catalog.measures),
                    llm
                  );
                  const sql = out.convertible ? safeExpression(out.sql) : null;
                  return sql ? ([[t.name, sql]] as [string, string][]) : [];
                } catch {
                  return [];
                }
              })
            );
            ai = new Map(found.flat());
          }
          result = ai.size ? convert(body.fileName, body.content, body.schema, base64, ai) : first;
          result.preview.ai = Object.fromEntries(ai);
        }
      } catch (err) {
        throw new HttpError(400, (err as Error).message);
      }
      if (!body.create) return result.preview;
      const { preview } = result;
      if (!preview.yaml) throw new HttpError(409, preview.issues[0] ?? 'Nothing could be converted.');
      if (preview.sources.length > MAX_SOURCES)
        throw new HttpError(400, `The model uses more than ${MAX_SOURCES} tables, the limit of a sub-project.`);
      const imported = importDesign(preview.sources[0], preview.yaml);
      const manual = preview.fields.filter((f) => f.status === 'manual');
      const brief = {
        ...imported.brief,
        title: body.subProject,
        assumptions: [`Imported from ${tool} (${body.fileName}).`],
        openQuestions: manual
          .slice(0, 50)
          .map((f) => `Not converted from ${tool}: ${f.name}. ${f.note} Source: ${f.source}`.slice(0, 1000)),
      };
      const sub = await projects.create(actor, { name: body.subProject }, parent.id);
      await db.query(
        `INSERT INTO gsb.source (project_id, full_name, added_by) SELECT $1, unnest($2::text[]), $3
         ON CONFLICT (project_id, full_name) DO NOTHING`,
        [sub.id, preview.sources, actor]
      );
      await projects.addDraft(
        actor,
        sub.id,
        { brief, summary: result.explanations.summary },
        { imported: body.fileName }
      );
      await designs.add(actor, sub.id, {
        name: imported.name,
        yaml: preview.yaml,
        explanations: result.explanations,
        tests: imported.tests,
        issues: imported.issues,
        origin: 'imported',
      });
      await db.query(
        `INSERT INTO gsb.audit_log (actor, action, project_id, target, outcome, detail)
         VALUES ($1, 'import_legacy_model', $2, $3, 'succeeded', $4)`,
        [
          actor,
          sub.id,
          body.fileName,
          {
            format: preview.format,
            converted: preview.fields.filter((f) => f.status === 'converted').length,
            review: preview.fields.filter((f) => f.status === 'review').length,
            manual: manual.length,
          },
        ]
      );
      return { parentId: parent.id, projectId: sub.id };
    })
  );
}
