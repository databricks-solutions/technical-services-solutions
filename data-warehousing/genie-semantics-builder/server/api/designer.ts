import type { Application, Request } from 'express';
import { z } from 'zod';
import type { LakebasePool } from '@databricks/appkit';
import { refineSchema } from '../../shared/brief';
import { saveDraftSchema } from '../../shared/designer';
import type { DesignDraft, DesignerView, Explanations, TestCase } from '../../shared/designer';
import { renderMetricView, validateMetricView } from '../../shared/metricView';
import type { MetricViewIssue } from '../../shared/metricView';
import { buildDesign, keepValidTests, toSourceProfiles } from '../designer/build';
import { callTool } from '../llm/llm';
import type { LlmDeps } from '../llm/llm';
import { designPrompt, designRequest, refineDesignPrompt, refineDesignRequest } from '../llm/prompts/designer';
import type { RunDeps } from '../sql/runner';
import { projectRepo } from './projects';
import { actorOf, handle, HttpError } from './http';
import { describeSources, MAX_SOURCES } from './readiness';

type Db = Pick<LakebasePool, 'query' | 'connect'>;

interface DraftRow {
  version: number;
  name: string;
  yaml: string;
  explanations: Explanations;
  tests: TestCase[];
  issues: MetricViewIssue[];
  origin: DesignDraft['origin'];
  status: DesignDraft['status'];
  created_by: string;
  created_at: Date;
}

const toDraft = (r: DraftRow): DesignDraft => ({
  version: r.version,
  name: r.name,
  yaml: r.yaml,
  explanations: r.explanations,
  tests: r.tests,
  issues: r.issues,
  origin: r.origin,
  status: r.status,
  createdBy: r.created_by,
  createdAt: r.created_at.toISOString(),
});

const COLUMNS = 'version, name, yaml, explanations, tests, issues, origin, status, created_by, created_at';

export type NewDraft = Pick<DesignDraft, 'name' | 'yaml' | 'explanations' | 'tests' | 'issues' | 'origin'>;

export function designerRepo(db: Db) {
  return {
    async view(projectId: string, version?: number): Promise<DesignerView> {
      const { rows } = await db.query<DraftRow>(
        `SELECT ${COLUMNS} FROM gsb.metric_view_draft WHERE project_id = $1 ORDER BY version DESC`,
        [projectId]
      );
      const pick = version === undefined ? rows[0] : rows.find((r) => r.version === version);
      if (version !== undefined && !pick) throw new HttpError(404, 'Version not found.');
      return {
        draft: pick ? toDraft(pick) : null,
        history: rows.map((r) => ({
          version: r.version,
          origin: r.origin,
          status: r.status,
          createdBy: r.created_by,
          createdAt: r.created_at.toISOString(),
        })),
      };
    },

    /** Adds the next version. With baseVersion, fails unless that version is still the latest. */
    async add(actor: string, projectId: string, d: NewDraft, baseVersion?: number): Promise<void> {
      const { rows } = await db.query(
        `WITH next AS (
           SELECT COALESCE(MAX(version), 0) AS latest FROM gsb.metric_view_draft WHERE project_id = $1
         ), d AS (
           INSERT INTO gsb.metric_view_draft (project_id, version, name, yaml, explanations, tests, issues, origin, created_by)
           SELECT $1, latest + 1, $2, $3, $4, $5, $6, $7, $8 FROM next WHERE $9::int IS NULL OR latest = $9::int
           RETURNING version
         ), a AS (
           INSERT INTO gsb.audit_log (actor, action, project_id, outcome, detail)
           SELECT $8, 'save_metric_view_draft', $1, 'succeeded', jsonb_build_object('version', version, 'origin', $7::text)
           FROM d
         )
         SELECT version FROM d`,
        [
          projectId,
          d.name,
          d.yaml,
          JSON.stringify(d.explanations),
          JSON.stringify(d.tests),
          JSON.stringify(d.issues),
          d.origin,
          actor,
          baseVersion ?? null,
        ]
      );
      if (!rows[0]) throw new HttpError(409, 'A newer version exists. Reload and apply your change again.');
    },
  };
}

const idParam = z.object({ id: z.uuid() });
const versionQuery = z.object({ version: z.coerce.number().int().positive().optional() });

export function registerDesignerRoutes(
  app: Application,
  db: Db,
  llmFor: (req: Request) => LlmDeps,
  runFor: (req: Request) => RunDeps
) {
  const projects = projectRepo(db);
  const repo = designerRepo(db);

  /** Confirmed brief plus live profiles of the project sources, read as the user. */
  async function context(req: Request) {
    const actor = actorOf(req);
    const project = await projects.get(actor, idParam.parse(req.params).id);
    const brief = await projects.latestBrief(project.id);
    if (brief?.status !== 'confirmed')
      throw new HttpError(409, 'Confirm the Semantic Brief before you design metrics.');
    const { rows } = await db.query<{ full_name: string }>(
      'SELECT full_name FROM gsb.source WHERE project_id = $1 ORDER BY full_name',
      [project.id]
    );
    if (!rows.length) throw new HttpError(409, 'The confirmed brief has no candidate sources.');
    if (rows.length > MAX_SOURCES) throw new HttpError(400, `Design with at most ${MAX_SOURCES} sources.`);
    const described = await describeSources(
      rows.map((r) => ({ fullName: r.full_name })),
      { actor, projectId: project.id },
      runFor(req)
    );
    const profiles = described.flatMap((d) => (d.profile ? [d.profile] : []));
    if (!profiles.length) throw new HttpError(403, 'You cannot read any of the project sources.');
    return { actor, project, brief: brief.brief, profiles };
  }

  const fromModel = (out: Parameters<typeof buildDesign>[0], ctx: Awaited<ReturnType<typeof context>>) => {
    const design = buildDesign(
      out,
      ctx.profiles.map((p) => p.fullName)
    );
    const yaml = renderMetricView(design.view);
    const { issues } = validateMetricView(yaml, toSourceProfiles(ctx.profiles));
    return { name: design.name, yaml, explanations: design.explanations, tests: design.tests, issues };
  };

  app.get(
    '/api/projects/:id/designs',
    handle(async (req) => {
      const project = await projects.get(actorOf(req), idParam.parse(req.params).id);
      return repo.view(project.id, versionQuery.parse(req.query).version);
    })
  );

  app.post(
    '/api/projects/:id/designs/generate',
    handle(async (req) => {
      const ctx = await context(req);
      const out = await callTool(designPrompt, designRequest(ctx.brief, ctx.profiles), llmFor(req));
      await repo.add(ctx.actor, ctx.project.id, { ...fromModel(out, ctx), origin: 'generated' });
      return repo.view(ctx.project.id);
    })
  );

  app.post(
    '/api/projects/:id/designs/refine',
    handle(async (req) => {
      const ctx = await context(req);
      const { instruction } = refineSchema.parse(req.body);
      const { draft } = await repo.view(ctx.project.id);
      if (!draft) throw new HttpError(409, 'Generate a design before you refine it.');
      const out = await callTool(
        refineDesignPrompt,
        refineDesignRequest(ctx.brief, ctx.profiles, draft, instruction),
        llmFor(req)
      );
      await repo.add(
        ctx.actor,
        ctx.project.id,
        { ...fromModel(out, ctx), name: draft.name, origin: 'refined' },
        draft.version
      );
      return repo.view(ctx.project.id);
    })
  );

  app.post(
    '/api/projects/:id/designs',
    handle(async (req) => {
      const { baseVersion, yaml } = saveDraftSchema.parse(req.body);
      const ctx = await context(req);
      const base = (await repo.view(ctx.project.id, baseVersion)).draft!;
      const { view, issues } = validateMetricView(yaml, toSourceProfiles(ctx.profiles));
      const names = new Set(view ? [...view.dimensions, ...view.measures].map((f) => f.name) : []);
      const keep = <T>(rec: Record<string, T>) => Object.fromEntries(Object.entries(rec).filter(([k]) => names.has(k)));
      const explanations = view
        ? {
            ...base.explanations,
            dimensions: keep(base.explanations.dimensions),
            measures: keep(base.explanations.measures),
          }
        : base.explanations;
      await repo.add(
        ctx.actor,
        ctx.project.id,
        {
          name: base.name,
          yaml,
          explanations,
          tests: view ? keepValidTests(base.tests, view) : base.tests,
          issues,
          origin: 'edited',
        },
        baseVersion
      );
      return repo.view(ctx.project.id);
    })
  );
}
