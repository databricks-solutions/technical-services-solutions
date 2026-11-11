import { createHash } from 'node:crypto';
import type { Application, Request } from 'express';
import { z } from 'zod';
import type { LakebasePool } from '@databricks/appkit';
import { askSchema, chatSchema } from '../../shared/genie';
import type {
  AgentScore,
  ChatAnswer,
  EvalRun,
  GenieCheck,
  GenieView,
  Tuning,
  TuningChange,
  TuningView,
} from '../../shared/genie';
import { validateMetricView } from '../../shared/metricView';
import type { SemanticBrief } from '../../shared/brief';
import type { TestCase } from '../../shared/designer';
import { createStatement, sandboxSchema, sandboxViewName } from '../designer/validate';
import type { GenieDeps } from '../genie/client';
import { readsView } from '../genie/onechat';
import { scoreAgent } from '../genie/score';
import { fieldsOf, keeps, toChange } from '../genie/tune';
import { callTool } from '../llm/llm';
import type { LlmDeps } from '../llm/llm';
import { tunePrompt, tuneRequest } from '../llm/prompts/tune';
import { spaceConfig } from '../genie/space';
import { fieldsUsed, verdictOf } from '../genie/verdict';
import { runStatement } from '../sql/runner';
import type { RunDeps } from '../sql/runner';
import type { UcDeps } from '../uc/metadata';
import { actorOf, handle, HttpError } from './http';
import { designerRepo } from './designer';
import { projectRepo } from './projects';

type Db = Pick<LakebasePool, 'query' | 'connect'>;
const idParam = z.object({ id: z.uuid() });
const spaceBody = z.object({
  statements: z.array(z.string().min(1).max(200_000)).min(1).max(10),
  config: z.string().min(1).max(3_500_000),
});
const MAX_CHECKS = 50;

interface CheckRow {
  id: string;
  engine: GenieCheck['engine'];
  read: GenieCheck['read'];
  version: number;
  question: string;
  expected: GenieCheck['expected'];
  verdict: GenieCheck['verdict'];
  detail: string;
  answer: string;
  sql: string | null;
  created_by: string;
  created_at: Date;
}

export function registerGenieRoutes(
  app: Application,
  db: Db,
  runFor: (req: Request) => RunDeps,
  genieFor: (req: Request) => GenieDeps,
  ucFor: (req: Request) => UcDeps,
  llmFor: (req: Request) => LlmDeps
) {
  const projects = projectRepo(db);
  const designs = designerRepo(db);

  /** The latest draft and its sandbox view. Genie works on a validated version only. */
  async function context(req: Request) {
    const actor = actorOf(req);
    const project = await projects.get(actor, idParam.parse(req.params).id);
    const draft = (await designs.view(project.id)).draft;
    const sandbox = sandboxSchema();
    const validated = draft?.status === 'validated' ? draft : null;
    const sandboxView = validated && sandbox ? sandboxViewName(sandbox, validated.name, project.id) : null;
    const { rows } = await db.query<{
      space_id: string;
      view_name: string;
      config_hash: string | null;
      created_at: Date;
    }>('SELECT space_id, view_name, config_hash, created_at FROM gsb.genie_space WHERE project_id = $1', [project.id]);
    return { actor, project, draft: validated, sandboxView, space: rows[0] ?? null };
  }

  type Ctx = Awaited<ReturnType<typeof context>>;

  /**
   * The text dimensions of the validated version, from the column types of its sandbox view in Unity Catalog, read
   * as the user. null when the view does not exist yet or cannot be read.
   */
  async function textDimensions(req: Request, ctx: Ctx): Promise<string[] | null> {
    if (!ctx.draft || !ctx.sandboxView) return null;
    const dims = new Set((validateMetricView(ctx.draft.yaml).view?.dimensions ?? []).map((d) => d.name));
    try {
      const { columns = [] } = await ucFor(req).table(ctx.sandboxView);
      return columns
        .filter((c) => c.name && dims.has(c.name) && /^(string|varchar|char)/i.test(c.type_text ?? ''))
        .map((c) => c.name!);
    } catch {
      return null;
    }
  }

  /** The space settings JSON the user reviews, built from the validated version. */
  const configOf = (
    sandboxView: string,
    brief: SemanticBrief | null,
    tests: TestCase[],
    text: string[] | null,
    kept: TuningChange[]
  ) => JSON.stringify(spaceConfig(sandboxView, brief, tests, text ?? [], kept), null, 2);

  const keptOf = async (projectId: string) =>
    (
      await db.query<{ change: TuningChange }>(
        `SELECT change FROM gsb.genie_tuning WHERE project_id = $1 AND status = 'kept' ORDER BY created_at`,
        [projectId]
      )
    ).rows.map((r) => r.change);

  /** The settings of the validated version with the kept changes, and one more change on trial. */
  async function settingsOf(req: Request, ctx: Ctx, trial?: TuningChange) {
    const brief = (await projects.latestBrief(ctx.project.id))?.brief ?? null;
    const text = await textDimensions(req, ctx);
    const kept = await keptOf(ctx.project.id);
    const config = configOf(ctx.sandboxView!, brief, ctx.draft!.tests, text, trial ? [...kept, trial] : kept);
    return { brief, text, config };
  }

  const trying = async (projectId: string) =>
    (await db.query(`SELECT 1 FROM gsb.genie_tuning WHERE project_id = $1 AND status = 'trying'`, [projectId]))
      .rowCount! > 0;
  const hashOf = (config: string) => createHash('sha256').update(config).digest('hex');

  async function view(req: Request): Promise<GenieView & { setup: string[]; config: string | null }> {
    const ctx = await context(req);
    const brief = await projects.latestBrief(ctx.project.id);
    const settings = ctx.draft && ctx.sandboxView ? await settingsOf(req, ctx) : null;
    const { rows } = await db.query<CheckRow>(
      `SELECT id, engine, read, version, question, expected, verdict, detail, answer, sql, created_by, created_at
       FROM gsb.genie_check WHERE project_id = $1 ORDER BY created_at DESC LIMIT ${MAX_CHECKS}`,
      [ctx.project.id]
    );
    return {
      version: ctx.draft?.version ?? null,
      sandboxView: ctx.sandboxView,
      space: ctx.space
        ? { spaceId: ctx.space.space_id, view: ctx.space.view_name, createdAt: ctx.space.created_at.toISOString() }
        : null,
      keyQuestions: brief?.brief.keyQuestions ?? [],
      setup: ctx.draft && ctx.sandboxView ? [createStatement(ctx.sandboxView, ctx.draft.yaml)] : [],
      config: settings?.config ?? null,
      checks: rows.map((r) => ({
        id: r.id,
        engine: r.engine,
        read: r.read,
        version: r.version,
        question: r.question,
        expected: r.expected,
        verdict: r.verdict,
        detail: r.detail,
        answer: r.answer,
        sql: r.sql,
        createdBy: r.created_by,
        createdAt: r.created_at.toISOString(),
      })),
    };
  }

  app.get('/api/projects/:id/genie', handle(view));

  /** The rule-based score of the Genie agent: the design, the brief, the tests and the space settings. */
  app.get(
    '/api/projects/:id/genie/score',
    handle(async (req): Promise<AgentScore | null> => {
      const ctx = await context(req);
      if (!ctx.draft || !ctx.sandboxView) return null;
      const { brief, text, config } = await settingsOf(req, ctx);
      return scoreAgent({
        view: validateMetricView(ctx.draft.yaml).view ?? null,
        brief,
        tests: ctx.draft.tests,
        matched: text,
        space: ctx.space
          ? { current: ctx.space.view_name === ctx.sandboxView && ctx.space.config_hash === hashOf(config) }
          : null,
      });
    })
  );

  /**
   * Creates the sandbox view of the validated version, as reviewed, then one Genie space on it with the settings
   * from the design, as the user. A space on the same view is kept, and its settings are replaced.
   */
  app.post(
    '/api/projects/:id/genie/space',
    handle(async (req) => {
      const { statements, config } = spaceBody.parse(req.body);
      const ctx = await context(req);
      if (!ctx.draft || !ctx.sandboxView) throw new HttpError(409, 'Validate the design before you ask Genie.');
      const setup = [createStatement(ctx.sandboxView, ctx.draft.yaml)];
      if (statements.length !== setup.length || statements.some((s, i) => s !== setup[i]))
        throw new HttpError(409, 'The SQL changed since you reviewed it. Review it again.');
      if (await trying(ctx.project.id))
        throw new HttpError(409, 'A change is on trial. Wait for its benchmark run to finish.');
      const brief = await projects.latestBrief(ctx.project.id);
      if (config !== (await settingsOf(req, ctx)).config)
        throw new HttpError(409, 'The space settings changed since you reviewed them. Review them again.');
      for (const s of setup)
        await runStatement(s, { actor: ctx.actor, projectId: ctx.project.id, approved: true }, runFor(req));

      const genie = genieFor(req);
      if (ctx.space?.view_name === ctx.sandboxView) {
        await genie.updateSpace(ctx.space.space_id, config);
        await db.query(
          `WITH up AS (UPDATE gsb.genie_space SET config_hash = $4 WHERE project_id = $2 RETURNING project_id)
           INSERT INTO gsb.audit_log (actor, action, project_id, target, outcome)
           SELECT $1, 'update_genie_space', project_id, $3, 'succeeded' FROM up`,
          [ctx.actor, ctx.project.id, ctx.space.space_id, hashOf(config)]
        );
      } else {
        const spaceId = await genie.createSpace(
          `${ctx.project.name} - Semantics Builder check`,
          (brief?.brief.businessGoal ?? '').slice(0, 1000),
          config
        );
        if (ctx.space) await genie.trashSpace(ctx.space.space_id).catch(() => undefined);
        await db.query(
          `WITH up AS (
             INSERT INTO gsb.genie_space (project_id, space_id, view_name, created_by, config_hash)
             VALUES ($1, $2, $3, $4, $5)
             ON CONFLICT (project_id) DO UPDATE
             SET space_id = $2, view_name = $3, created_by = $4, config_hash = $5, created_at = now()
             RETURNING project_id
           )
           INSERT INTO gsb.audit_log (actor, action, project_id, target, outcome)
           SELECT $4, 'create_genie_space', project_id, $2, 'succeeded' FROM up`,
          [ctx.project.id, spaceId, ctx.sandboxView, ctx.actor, hashOf(config)]
        );
      }
      return view(req);
    })
  );

  /** Asks Genie one question in a new conversation, then compares its SQL with the expected fields. */
  app.post(
    '/api/projects/:id/genie/ask',
    handle(async (req) => {
      const { question, expected, engine } = askSchema.parse(req.body);
      const ctx = await context(req);
      if (!ctx.draft || !ctx.sandboxView) throw new HttpError(409, 'Validate the design first.');
      if (engine === 'space' && !ctx.space) throw new HttpError(409, 'Create the Genie space first.');
      const fields = validateMetricView(ctx.draft.yaml).view;
      const names = {
        measures: fields?.measures.map((m) => m.name) ?? [],
        dimensions: fields?.dimensions.map((d) => d.name) ?? [],
      };
      if (expected) {
        const unknown = [
          ...expected.measures.filter((m) => !names.measures.includes(m)),
          ...expected.dimensions.filter((d) => !names.dimensions.includes(d)),
        ];
        if (unknown.length) throw new HttpError(400, `Not fields of the view: ${unknown.join(', ')}`);
      }
      let result: {
        verdict: GenieCheck['verdict'];
        detail: string;
        answer: string;
        sql: string | null;
        read?: GenieCheck['read'];
      };
      try {
        if (engine === 'one') {
          // Genie One is not bound to a space, so the question names the sandbox view of this version.
          const view = ctx.sandboxView;
          const answer = await genieFor(req).askOne(`${question}\n\nAnswer with the metric view ${view} only.`);
          const v = verdictOf(answer.sql, names, expected);
          const other = answer.sql && !readsView(answer.sql, view);
          result = {
            ...(other ? { verdict: 'different' as const, detail: `Genie One did not read ${view}. ${v.detail}` } : v),
            answer: answer.text.slice(0, 20_000),
            sql: answer.sql,
            read: { assets: answer.assets, snippets: answer.snippets },
          };
        } else {
          const answer = await genieFor(req).ask(ctx.space.space_id, question);
          result = { ...verdictOf(answer.sql, names, expected), answer: answer.text.slice(0, 20_000), sql: answer.sql };
        }
      } catch (err) {
        result = { verdict: 'error', detail: (err as Error).message.slice(0, 500), answer: '', sql: null };
      }
      await db.query(
        `INSERT INTO gsb.genie_check
           (project_id, version, question, expected, verdict, detail, answer, sql, created_by, engine, read)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)`,
        [
          ctx.project.id,
          ctx.draft.version,
          question,
          expected ? JSON.stringify(expected) : null,
          result.verdict,
          result.detail,
          result.answer,
          result.sql,
          ctx.actor,
          engine,
          result.read ? JSON.stringify(result.read) : null,
        ]
      );
      return view(req);
    })
  );

  /**
   * The Genie chat panel. Genie Agent asks the space on the sandbox view, with follow-ups. Genie One answers each
   * question alone. The app stores nothing: the conversation stays in Databricks, as the user.
   */
  app.post(
    '/api/projects/:id/genie/chat',
    handle(async (req): Promise<ChatAnswer> => {
      const { question, engine, conversationId } = chatSchema.parse(req.body);
      const ctx = await context(req);
      if (!ctx.draft || !ctx.sandboxView) throw new HttpError(409, 'Validate the design before you ask Genie.');
      const parsed = validateMetricView(ctx.draft.yaml).view;
      const names = {
        measures: parsed?.measures.map((m) => m.name) ?? [],
        dimensions: parsed?.dimensions.map((d) => d.name) ?? [],
      };
      const fields = (sql: string | null) => (sql ? fieldsUsed(sql, names) : { measures: [], dimensions: [] });
      if (engine === 'one') {
        const a = await genieFor(req).askOne(`${question}\n\nAnswer with the metric view ${ctx.sandboxView} only.`);
        return {
          conversationId: null,
          text: a.text.slice(0, 20_000),
          sql: a.sql,
          fields: fields(a.sql),
          table: null,
          read: { assets: a.assets, snippets: a.snippets },
          suggested: [],
        };
      }
      if (!ctx.space) throw new HttpError(409, 'Create the Genie space first: Optimize, Test with Genie.');
      const a = await genieFor(req).chat(ctx.space.space_id, question, conversationId);
      return { ...a, text: a.text.slice(0, 20_000), fields: fields(a.sql), read: null };
    })
  );

  // ---- i3: optimize the Genie agent with the benchmarks, one approved change at a time ----

  const tuningParam = idParam.extend({ tuningId: z.uuid() });
  const RUN_TIMEOUT_MS = 15 * 60_000;

  interface EvalRow {
    id: string;
    space_id: string;
    eval_run_id: string;
    config_hash: string;
    tuning_id: string | null;
    status: EvalRun['status'];
    num_questions: number;
    num_correct: number;
    num_needs_review: number;
    results: { question: string; assessment: string; resultId: string }[];
    error: string | null;
    created_at: Date;
  }
  interface TuningRow {
    id: string;
    question: string;
    change: TuningChange;
    rationale: string;
    status: Tuning['status'];
    before_correct: number | null;
    after_correct: number | null;
    num_questions: number | null;
    error: string | null;
    created_by: string;
    created_at: Date;
  }
  const toTuning = (r: TuningRow): Tuning => ({
    id: r.id,
    question: r.question,
    change: r.change,
    rationale: r.rationale,
    status: r.status,
    beforeCorrect: r.before_correct,
    afterCorrect: r.after_correct,
    numQuestions: r.num_questions,
    error: r.error,
    createdBy: r.created_by,
    createdAt: r.created_at.toISOString(),
  });
  const audit = (actor: string, action: string, projectId: string, target: string, detail?: unknown) =>
    db.query(
      `INSERT INTO gsb.audit_log (actor, action, project_id, target, outcome, detail) VALUES ($1, $2, $3, $4, 'succeeded', $5)`,
      [actor, action, projectId, target, detail ?? null]
    );

  /** Puts the space back to the kept settings, after a change that did not help. */
  async function restore(req: Request, ctx: Ctx) {
    const { config } = await settingsOf(req, ctx);
    await genieFor(req).updateSpace(ctx.space.space_id, config);
    await db.query('UPDATE gsb.genie_space SET config_hash = $2 WHERE project_id = $1', [
      ctx.project.id,
      hashOf(config),
    ]);
  }

  /** Reads the running benchmark runs from Genie. A finished trial run keeps or reverts its change. */
  async function advance(req: Request, ctx: Ctx) {
    const { rows } = await db.query<EvalRow & { tuning_status: string | null; before_correct: number | null }>(
      `SELECT e.*, t.status AS tuning_status, t.before_correct FROM gsb.genie_eval e
       LEFT JOIN gsb.genie_tuning t ON t.id = e.tuning_id
       WHERE e.project_id = $1 AND e.status = 'running'`,
      [ctx.project.id]
    );
    const genie = genieFor(req);
    for (const run of rows) {
      let done: { status: 'done' | 'failed'; counts?: Awaited<ReturnType<GenieDeps['evalRun']>>; error?: string };
      try {
        const counts = await genie.evalRun(run.space_id, run.eval_run_id);
        if (counts.status === 'DONE') done = { status: 'done', counts };
        else if (/RUNNING|PENDING|QUEUED|CREATED/.test(counts.status)) {
          if (Date.now() - run.created_at.getTime() < RUN_TIMEOUT_MS) continue;
          done = { status: 'failed', error: 'The benchmark run took more than 15 minutes.' };
        } else done = { status: 'failed', error: `The benchmark run ended as ${counts.status}.` };
      } catch (err) {
        done = { status: 'failed', error: (err as Error).message.slice(0, 500) };
      }
      const results =
        done.status === 'done'
          ? (await genie.evalResults(run.space_id, run.eval_run_id)).map((r) => ({
              question: r.question,
              assessment: r.assessment,
              resultId: r.resultId,
            }))
          : [];
      const updated = await db.query(
        `UPDATE gsb.genie_eval SET status = $2, num_questions = $3, num_correct = $4, num_needs_review = $5,
           results = $6, error = $7, finished_at = now()
         WHERE id = $1 AND status = 'running' RETURNING id`,
        [
          run.id,
          done.status,
          done.counts?.numQuestions ?? 0,
          done.counts?.numCorrect ?? 0,
          done.counts?.numNeedsReview ?? 0,
          JSON.stringify(results),
          done.error ?? null,
        ]
      );
      // Another request finished this run first.
      if (!updated.rowCount || !run.tuning_id || run.tuning_status !== 'trying') continue;
      const after = done.counts?.numCorrect ?? null;
      const kept = done.status === 'done' && after !== null && keeps(run.before_correct ?? 0, after);
      const status = kept ? 'kept' : done.status === 'done' ? 'reverted' : 'failed';
      await db.query(
        `UPDATE gsb.genie_tuning SET status = $2, after_correct = $3, error = $4, decided_at = now()
         WHERE id = $1 AND status = 'trying'`,
        [run.tuning_id, status, after, done.error ?? null]
      );
      if (!kept) await restore(req, ctx);
      await audit(ctx.actor, kept ? 'keep_genie_change' : 'revert_genie_change', ctx.project.id, run.tuning_id, {
        before: run.before_correct,
        after,
      });
    }
  }

  async function tuningView(req: Request, ctx: Ctx): Promise<TuningView> {
    const settings = ctx.draft && ctx.sandboxView ? await settingsOf(req, ctx) : null;
    const hash = settings ? hashOf(settings.config) : null;
    const [runs, tunings] = await Promise.all([
      db.query<EvalRow>(`SELECT * FROM gsb.genie_eval WHERE project_id = $1 ORDER BY created_at DESC LIMIT 10`, [
        ctx.project.id,
      ]),
      db.query<TuningRow>(`SELECT * FROM gsb.genie_tuning WHERE project_id = $1 ORDER BY created_at DESC LIMIT 20`, [
        ctx.project.id,
      ]),
    ]);
    return {
      runs: runs.rows.map((r) => ({
        id: r.id,
        status: r.status,
        numQuestions: r.num_questions,
        numCorrect: r.num_correct,
        numNeedsReview: r.num_needs_review,
        results: r.results.map(({ question, assessment }) => ({ question, assessment })),
        tuningId: r.tuning_id,
        current: r.config_hash === hash,
        error: r.error,
        createdAt: r.created_at.toISOString(),
      })),
      tunings: tunings.rows.map(toTuning),
      benchmarks: ctx.draft?.tests.filter((t) => t.expect).length ?? 0,
      spaceCurrent: !!ctx.space && ctx.space.view_name === ctx.sandboxView && ctx.space.config_hash === hash,
    };
  }

  /** The latest finished run on the settings in the space now. */
  async function baseline(req: Request, ctx: Ctx) {
    const { config } = await settingsOf(req, ctx);
    const { rows } = await db.query<EvalRow>(
      `SELECT * FROM gsb.genie_eval WHERE project_id = $1 AND status = 'done' AND config_hash = $2
       ORDER BY created_at DESC LIMIT 1`,
      [ctx.project.id, hashOf(config)]
    );
    return rows[0] ?? null;
  }

  async function ready(req: Request) {
    const ctx = await context(req);
    if (!ctx.draft || !ctx.sandboxView) throw new HttpError(409, 'Validate the design first.');
    if (!ctx.space) throw new HttpError(409, 'Create the Genie space first.');
    return ctx;
  }

  app.get(
    '/api/projects/:id/genie/tuning',
    handle(async (req) => {
      const ctx = await context(req);
      if (ctx.space && ctx.draft && ctx.sandboxView) await advance(req, ctx);
      return tuningView(req, await context(req));
    })
  );

  /** Runs all benchmarks of the space, as the user. */
  app.post(
    '/api/projects/:id/genie/eval',
    handle(async (req) => {
      const ctx = await ready(req);
      const view = await tuningView(req, ctx);
      if (!view.benchmarks)
        throw new HttpError(409, 'Add a test with an expected value first. It becomes a benchmark.');
      if (!view.spaceCurrent)
        throw new HttpError(409, 'The space does not have the settings of this design. Update the space first.');
      if (view.runs.some((r) => r.status === 'running')) throw new HttpError(409, 'A benchmark run is still running.');
      const runId = await genieFor(req).startEval(ctx.space.space_id);
      const { config } = await settingsOf(req, ctx);
      await db.query(
        `INSERT INTO gsb.genie_eval (project_id, space_id, eval_run_id, config_hash, created_by) VALUES ($1, $2, $3, $4, $5)`,
        [ctx.project.id, ctx.space.space_id, runId, hashOf(config), ctx.actor]
      );
      await audit(ctx.actor, 'run_genie_benchmarks', ctx.project.id, ctx.space.space_id);
      return tuningView(req, ctx);
    })
  );

  /**
   * The AI suggests one change for a wrong answer of the latest run. It sees the question, the expected SQL, the SQL
   * of Genie, the fields and the instructions; never the result values.
   */
  app.post(
    '/api/projects/:id/genie/tuning/suggest',
    handle(async (req) => {
      const { question } = z.object({ question: z.string().trim().min(1).max(1000) }).parse(req.body);
      const ctx = await ready(req);
      const run = await baseline(req, ctx);
      const wrong = run?.results.find((r) => r.question === question && r.assessment !== 'GOOD');
      if (!run || !wrong) throw new HttpError(409, 'Run the benchmarks again: this answer is not in the latest run.');
      const detail = (await genieFor(req).evalResults(run.space_id, run.eval_run_id)).find(
        (r) => r.resultId === wrong.resultId
      );
      const view = validateMetricView(ctx.draft!.yaml).view;
      if (!view) throw new HttpError(409, 'The design does not parse.');
      const { config } = await settingsOf(req, ctx);
      const instructions = (
        JSON.parse(config) as { instructions: { text_instructions: { content: string[] }[] } }
      ).instructions.text_instructions.flatMap((t) => t.content.join('').split('\n'));
      const out = await callTool(
        tunePrompt,
        tuneRequest({
          question,
          expectedSql: detail?.expectedSql ?? null,
          genieSql: detail?.actualSql ?? null,
          fields: fieldsOf(view),
          instructions,
        }),
        llmFor(req)
      );
      let change: TuningChange;
      try {
        change = toChange(out, view, ctx.draft!.tests);
      } catch (err) {
        throw new HttpError(422, (err as Error).message);
      }
      const { rows } = await db.query<TuningRow>(
        `INSERT INTO gsb.genie_tuning (project_id, question, change, rationale, created_by)
         VALUES ($1, $2, $3, $4, $5) RETURNING *`,
        [ctx.project.id, question, change, out.rationale, ctx.actor]
      );
      return { tuning: toTuning(rows[0]), config: (await settingsOf(req, ctx, change)).config };
    })
  );

  /** The settings with the change, for the user to examine before it runs. */
  app.get(
    '/api/projects/:id/genie/tuning/:tuningId',
    handle(async (req) => {
      const { tuningId } = tuningParam.parse(req.params);
      const ctx = await ready(req);
      const { rows } = await db.query<TuningRow>(`SELECT * FROM gsb.genie_tuning WHERE id = $1 AND project_id = $2`, [
        tuningId,
        ctx.project.id,
      ]);
      if (!rows[0]) throw new HttpError(404, 'Change not found.');
      return { tuning: toTuning(rows[0]), config: (await settingsOf(req, ctx, rows[0].change)).config };
    })
  );

  /**
   * The user approved the change: the app updates the space and runs the benchmarks again. When the run ends, the
   * app keeps the change if more answers are correct, else it restores the settings.
   */
  app.post(
    '/api/projects/:id/genie/tuning/:tuningId/apply',
    handle(async (req) => {
      const { tuningId } = tuningParam.parse(req.params);
      const { config } = z.object({ config: z.string().min(1).max(3_500_000) }).parse(req.body);
      const ctx = await ready(req);
      const { rows } = await db.query<TuningRow>(
        `SELECT * FROM gsb.genie_tuning WHERE id = $1 AND project_id = $2 AND status = 'proposed'`,
        [tuningId, ctx.project.id]
      );
      if (!rows[0]) throw new HttpError(409, 'This change is not open any more.');
      const view = await tuningView(req, ctx);
      if (!view.spaceCurrent) throw new HttpError(409, 'Update the space first.');
      if (view.runs.some((r) => r.status === 'running')) throw new HttpError(409, 'A benchmark run is still running.');
      const base = await baseline(req, ctx);
      if (!base) throw new HttpError(409, 'Run the benchmarks first, to measure the accuracy before the change.');
      const trial = (await settingsOf(req, ctx, rows[0].change)).config;
      if (config !== trial)
        throw new HttpError(409, 'The settings changed since you examined them. Examine them again.');
      const genie = genieFor(req);
      await db.query(
        `UPDATE gsb.genie_tuning SET status = 'trying', before_correct = $2, num_questions = $3 WHERE id = $1`,
        [tuningId, base.num_correct, base.num_questions]
      );
      try {
        await genie.updateSpace(ctx.space.space_id, trial);
        await db.query('UPDATE gsb.genie_space SET config_hash = $2 WHERE project_id = $1', [
          ctx.project.id,
          hashOf(trial),
        ]);
        const runId = await genie.startEval(ctx.space.space_id);
        await db.query(
          `INSERT INTO gsb.genie_eval (project_id, space_id, eval_run_id, config_hash, tuning_id, created_by)
           VALUES ($1, $2, $3, $4, $5, $6)`,
          [ctx.project.id, ctx.space.space_id, runId, hashOf(trial), tuningId, ctx.actor]
        );
      } catch (err) {
        await db.query(`UPDATE gsb.genie_tuning SET status = 'failed', error = $2, decided_at = now() WHERE id = $1`, [
          tuningId,
          (err as Error).message.slice(0, 500),
        ]);
        await restore(req, ctx).catch(() => undefined);
        throw err;
      }
      await audit(ctx.actor, 'try_genie_change', ctx.project.id, tuningId, { change: rows[0].change });
      return tuningView(req, await context(req));
    })
  );

  app.post(
    '/api/projects/:id/genie/tuning/:tuningId/dismiss',
    handle(async (req) => {
      const { tuningId } = tuningParam.parse(req.params);
      const ctx = await ready(req);
      await db.query(
        `UPDATE gsb.genie_tuning SET status = 'dismissed', decided_at = now()
         WHERE id = $1 AND project_id = $2 AND status = 'proposed'`,
        [tuningId, ctx.project.id]
      );
      return tuningView(req, ctx);
    })
  );
}
