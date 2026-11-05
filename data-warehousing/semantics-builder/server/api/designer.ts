import type { Application, Request } from 'express';
import { z } from 'zod';
import type { LakebasePool } from '@databricks/appkit';
import { refineSchema } from '../../shared/brief';
import { saveDraftSchema, validateSchema } from '../../shared/designer';
import type {
  DesignDraft,
  DesignerView,
  Explanations,
  TestCase,
  TestResult,
  ValidationPlan,
  ValidationRun,
} from '../../shared/designer';
import { renderMetricView, validateMetricView } from '../../shared/metricView';
import type { MetricViewIssue } from '../../shared/metricView';
import { buildDesign, keepValidTests, toSourceProfiles } from '../designer/build';
import { callTool } from '../llm/llm';
import type { LlmDeps } from '../llm/llm';
import {
  applyPatternPrompt,
  applyPatternRequest,
  designPrompt,
  designRequest,
  refineDesignPrompt,
  refineDesignRequest,
} from '../llm/prompts/designer';
import type { Pattern } from '../../shared/patterns';
import {
  compareRows,
  createStatement,
  dropStatement,
  expandedQuery,
  measureQuery,
  sandboxSchema,
  sandboxViewName,
} from '../designer/validate';
import { certifiedIssues, dictionaryContext } from '../dictionary/match';
import { loadDictionary } from '../dictionary/store';
import { runStatement } from '../sql/runner';
import type { RunDeps } from '../sql/runner';
import { projectRepo } from './projects';
import { actorOf, handle, HttpError } from './http';
import { describeSources, MAX_SOURCES } from './readiness';
import type { UcDeps } from '../uc/metadata';

type Db = Pick<LakebasePool, 'query' | 'connect'>;

interface DraftRow {
  id: string;
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

const COLUMNS = 'id, version, name, yaml, explanations, tests, issues, origin, status, created_by, created_at';

interface RunRow {
  id: string;
  status: ValidationRun['status'];
  sandbox_view: string;
  results: TestResult[];
  error: string | null;
  created_by: string;
  created_at: Date;
}

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
      const runs = pick
        ? await db.query<RunRow>(
            `SELECT id, status, sandbox_view, results, error, created_by, created_at FROM gsb.validation_run
             WHERE draft_id = $1 ORDER BY created_at DESC LIMIT 1`,
            [pick.id]
          )
        : { rows: [] };
      const run = runs.rows[0];
      return {
        draft: pick ? toDraft(pick) : null,
        validation:
          run && pick
            ? {
                id: run.id,
                version: pick.version,
                status: run.status,
                sandboxView: run.sandbox_view,
                results: run.results,
                error: run.error,
                cleanup: run.status === 'running' ? [] : [dropStatement(run.sandbox_view)],
                createdBy: run.created_by,
                createdAt: run.created_at.toISOString(),
              }
            : null,
        history: rows.map((r) => ({
          version: r.version,
          origin: r.origin,
          status: r.status,
          createdBy: r.created_by,
          createdAt: r.created_at.toISOString(),
        })),
      };
    },

    /** Starts a run for the latest version only. Returns the run id. */
    async startRun(actor: string, projectId: string, version: number, sandboxView: string, statements: string[]) {
      const { rows } = await db.query<{ id: string }>(
        `WITH d AS (
           SELECT id FROM gsb.metric_view_draft WHERE project_id = $1 AND version = $2
             AND version = (SELECT MAX(version) FROM gsb.metric_view_draft WHERE project_id = $1)
         ), r AS (
           INSERT INTO gsb.validation_run (draft_id, sandbox_view, statements, status, created_by)
           SELECT id, $3, $4::text[], 'running', $5 FROM d RETURNING id
         ), a AS (
           INSERT INTO gsb.audit_log (actor, action, project_id, target, outcome, detail)
           SELECT $5, 'validate_metric_view', $1, $3, 'requested', jsonb_build_object('version', $2::int) FROM r
         )
         SELECT id FROM r`,
        [projectId, version, sandboxView, statements, actor]
      );
      if (!rows[0]) throw new HttpError(409, 'Only the latest version can be validated.');
      return rows[0].id;
    },

    async finishRun(id: string, status: 'passed' | 'failed', results: TestResult[], error: string | null) {
      await db.query(
        `WITH r AS (
           UPDATE gsb.validation_run SET status = $2, results = $3, error = $4, finished_at = now()
           WHERE id = $1 RETURNING draft_id
         )
         UPDATE gsb.metric_view_draft SET status = 'validated' WHERE $2 = 'passed' AND id = (SELECT draft_id FROM r)`,
        [id, status, JSON.stringify(results), error]
      );
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
const versionParam = idParam.extend({ version: z.coerce.number().int().positive() });
const versionQuery = z.object({ version: z.coerce.number().int().positive().optional() });

export function registerDesignerRoutes(
  app: Application,
  db: Db,
  llmFor: (req: Request) => LlmDeps,
  runFor: (req: Request) => RunDeps,
  ucFor: (req: Request) => UcDeps,
  patterns: Pattern[] = []
) {
  const projects = projectRepo(db);
  const repo = designerRepo(db);
  const bySlug = new Map(patterns.map((p) => [p.slug, p]));

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
      ucFor(req)
    );
    const profiles = described.flatMap((d) => (d.profile ? [d.profile] : []));
    if (!profiles.length) throw new HttpError(403, 'You cannot read any of the project sources.');
    const dictionary = await loadDictionary(db, project.id);
    return { actor, project, brief: brief.brief, profiles, dictionary };
  }

  const fromModel = (out: Parameters<typeof buildDesign>[0], ctx: Awaited<ReturnType<typeof context>>) => {
    const design = buildDesign(
      out,
      ctx.profiles.map((p) => p.fullName)
    );
    const yaml = renderMetricView(design.view);
    const { view, issues } = validateMetricView(yaml, toSourceProfiles(ctx.profiles));
    return {
      name: design.name,
      yaml,
      explanations: design.explanations,
      tests: design.tests,
      issues: [...issues, ...(view ? certifiedIssues(view, ctx.dictionary) : [])],
    };
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
      const out = await callTool(
        designPrompt,
        designRequest(ctx.brief, ctx.profiles, dictionaryContext(ctx.dictionary, ctx.profiles)),
        llmFor(req)
      );
      await repo.add(ctx.actor, ctx.project.id, { ...fromModel(out, ctx), origin: 'generated' });
      return repo.view(ctx.project.id);
    })
  );

  app.post(
    '/api/projects/:id/patterns/:slug/apply',
    handle(async (req) => {
      const pattern = bySlug.get(z.object({ slug: z.string() }).parse(req.params).slug);
      if (!pattern) throw new HttpError(404, 'Pattern not found.');
      const ctx = await context(req);
      const out = await callTool(
        applyPatternPrompt,
        applyPatternRequest(ctx.brief, ctx.profiles, pattern),
        llmFor(req)
      );
      const missing = out.roles.filter((r) => r.mappedTo === null);
      if (missing.length)
        throw new HttpError(
          409,
          `No project column fits ${missing.map((r) => `${r.role} (${r.reason})`).join('; ')}. Add a source that has it, then try again.`
        );
      const design = fromModel(out, ctx);
      const current = (await repo.view(ctx.project.id)).draft;
      const roles = out.roles.map((r) => `${r.role}: ${r.mappedTo ?? ''}`).join('; ');
      await repo.add(ctx.actor, ctx.project.id, {
        ...design,
        name: current?.name ?? design.name,
        explanations: {
          ...design.explanations,
          summary: `Adapted from the pattern "${pattern.title}". Roles: ${roles}. ${design.explanations.summary}`,
        },
        origin: 'pattern',
      });
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
        refineDesignRequest(
          ctx.brief,
          ctx.profiles,
          draft,
          instruction,
          dictionaryContext(ctx.dictionary, ctx.profiles)
        ),
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
      const checked = validateMetricView(yaml, toSourceProfiles(ctx.profiles));
      const view = checked.view;
      const issues = [...checked.issues, ...(view ? certifiedIssues(view, ctx.dictionary) : [])];
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

  const planFor = (project: { id: string }, draft: DesignDraft): ValidationPlan => {
    const sandbox = sandboxSchema();
    if (!sandbox) throw new HttpError(503, 'Validation is not configured. Set the sandbox_schema bundle variable.');
    const sandboxView = sandboxViewName(sandbox, draft.name, project.id);
    try {
      return { sandboxView, statements: [createStatement(sandboxView, draft.yaml)] };
    } catch (err) {
      throw new HttpError(400, (err as Error).message);
    }
  };

  /** The latest draft, ready for validation: no errors, at least one test. */
  async function validatable(req: Request) {
    const actor = actorOf(req);
    const { id, version } = versionParam.parse(req.params);
    const project = await projects.get(actor, id);
    const view = await repo.view(project.id, version);
    const draft = view.draft!;
    if (view.history[0]?.version !== version) throw new HttpError(409, 'Only the latest version can be validated.');
    if (draft.issues.some((i) => i.severity === 'error'))
      throw new HttpError(409, 'Fix the errors in the YAML before you validate.');
    if (!draft.tests.length) throw new HttpError(409, 'Add test cases before you validate.');
    return { actor, project, draft, plan: planFor(project, draft) };
  }

  app.post(
    '/api/projects/:id/designs/:version/validation/drop',
    handle(async (req) => {
      const actor = actorOf(req);
      const { id, version } = versionParam.parse(req.params);
      const { statements } = validateSchema.parse(req.body);
      const project = await projects.get(actor, id);
      const cleanup = (await repo.view(project.id, version)).validation?.cleanup ?? [];
      if (!cleanup.length || statements.length !== cleanup.length || statements.some((s, i) => s !== cleanup[i]))
        throw new HttpError(409, 'The SQL changed since you reviewed it. Review it again.');
      for (const s of cleanup) await runStatement(s, { actor, projectId: project.id, approved: true }, runFor(req));
      return { removed: true };
    })
  );

  app.get(
    '/api/projects/:id/designs/:version/validation',
    handle(async (req): Promise<ValidationPlan> => (await validatable(req)).plan)
  );

  app.post(
    '/api/projects/:id/designs/:version/validation',
    handle(async (req) => {
      const { statements } = validateSchema.parse(req.body);
      const { actor, project, draft, plan } = await validatable(req);
      if (statements.length !== plan.statements.length || statements.some((s, i) => s !== plan.statements[i]))
        throw new HttpError(409, 'The SQL changed since you reviewed it. Review it again.');
      const view = validateMetricView(draft.yaml).view!;
      const runId = await repo.startRun(actor, project.id, draft.version, plan.sandboxView, plan.statements);
      const run = runFor(req);
      const ctx = { actor, projectId: project.id };

      try {
        for (const s of plan.statements) await runStatement(s, { ...ctx, approved: true }, run);
      } catch (err) {
        await repo.finishRun(
          runId,
          'failed',
          [],
          `Creating the sandbox view failed: ${(err as Error).message.slice(0, 1000)}`
        );
        return repo.view(project.id, draft.version);
      }

      const results = await Promise.all(
        draft.tests.map(async (test): Promise<TestResult> => {
          const measureSql = measureQuery(plan.sandboxView, test);
          // Window measures have no plain SQL form; compare the other columns and say so.
          const plain = test.measures.filter((m) => expandedQuery(view, { ...test, measures: [m] }) !== null);
          const skipped = test.measures.filter((m) => !plain.includes(m));
          const expandedSql = plain.length ? expandedQuery(view, { ...test, measures: plain }) : null;
          const note = skipped.length
            ? ` ${skipped.join(', ')} ran but plain SQL cannot express them, so they were not compared.`
            : '';
          try {
            const [actual, expected] = await Promise.all([
              runStatement(measureSql, { ...ctx, approved: false }, run),
              expandedSql ? runStatement(expandedSql, { ...ctx, approved: false }, run) : null,
            ]);
            if (!expected)
              return {
                name: test.name,
                status: 'passed',
                rows: actual.rows.length,
                detail: `The query ran.${note}`,
                measureSql,
                expandedSql,
              };
            const columns = [...test.dimensions, ...plain];
            const all = [...test.dimensions, ...test.measures];
            const keep = columns.map((c) => all.indexOf(c));
            const result = compareRows(
              columns,
              actual.rows.map((r) => keep.map((i) => r[i] ?? null)),
              expected.rows
            );
            return { name: test.name, ...result, detail: `${result.detail}${note}`, measureSql, expandedSql };
          } catch (err) {
            return {
              name: test.name,
              status: 'error',
              rows: 0,
              detail: (err as Error).message.slice(0, 500),
              measureSql,
              expandedSql,
            };
          }
        })
      );
      await repo.finishRun(runId, results.every((r) => r.status === 'passed') ? 'passed' : 'failed', results, null);
      return repo.view(project.id, draft.version);
    })
  );
}
