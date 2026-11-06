import type { Application, Request } from 'express';
import { z } from 'zod';
import type { LakebasePool } from '@databricks/appkit';
import { askSchema } from '../../shared/genie';
import type { GenieCheck, GenieView } from '../../shared/genie';
import { validateMetricView } from '../../shared/metricView';
import { createStatement, sandboxSchema, sandboxViewName } from '../designer/validate';
import type { GenieDeps } from '../genie/client';
import { readsView } from '../genie/onechat';
import { verdictOf } from '../genie/verdict';
import { runStatement } from '../sql/runner';
import type { RunDeps } from '../sql/runner';
import { actorOf, handle, HttpError } from './http';
import { designerRepo } from './designer';
import { projectRepo } from './projects';

type Db = Pick<LakebasePool, 'query' | 'connect'>;
const idParam = z.object({ id: z.uuid() });
const spaceBody = z.object({ statements: z.array(z.string().min(1).max(200_000)).min(1).max(10) });
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
  genieFor: (req: Request) => GenieDeps
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
    const { rows } = await db.query<{ space_id: string; view_name: string; created_at: Date }>(
      'SELECT space_id, view_name, created_at FROM gsb.genie_space WHERE project_id = $1',
      [project.id]
    );
    return { actor, project, draft: validated, sandboxView, space: rows[0] ?? null };
  }

  async function view(req: Request): Promise<GenieView & { setup: string[] }> {
    const ctx = await context(req);
    const brief = await projects.latestBrief(ctx.project.id);
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

  /**
   * Creates the sandbox view of the validated version, as reviewed, then one Genie space on it, as the user.
   * A space that already points at the same view is kept; the view itself is replaced in place.
   */
  app.post(
    '/api/projects/:id/genie/space',
    handle(async (req) => {
      const { statements } = spaceBody.parse(req.body);
      const ctx = await context(req);
      if (!ctx.draft || !ctx.sandboxView) throw new HttpError(409, 'Validate the design before you ask Genie.');
      const setup = [createStatement(ctx.sandboxView, ctx.draft.yaml)];
      if (statements.length !== setup.length || statements.some((s, i) => s !== setup[i]))
        throw new HttpError(409, 'The SQL changed since you reviewed it. Review it again.');
      for (const s of setup)
        await runStatement(s, { actor: ctx.actor, projectId: ctx.project.id, approved: true }, runFor(req));

      if (ctx.space?.view_name !== ctx.sandboxView) {
        const genie = genieFor(req);
        const brief = await projects.latestBrief(ctx.project.id);
        const spaceId = await genie.createSpace(
          ctx.sandboxView,
          `${ctx.project.name} - Semantics Builder check`,
          (brief?.brief.businessGoal ?? '').slice(0, 1000)
        );
        if (ctx.space) await genie.trashSpace(ctx.space.space_id).catch(() => undefined);
        await db.query(
          `WITH up AS (
             INSERT INTO gsb.genie_space (project_id, space_id, view_name, created_by) VALUES ($1, $2, $3, $4)
             ON CONFLICT (project_id) DO UPDATE SET space_id = $2, view_name = $3, created_by = $4, created_at = now()
             RETURNING project_id
           )
           INSERT INTO gsb.audit_log (actor, action, project_id, target, outcome)
           SELECT $4, 'create_genie_space', project_id, $2, 'succeeded' FROM up`,
          [ctx.project.id, spaceId, ctx.sandboxView, ctx.actor]
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
}
