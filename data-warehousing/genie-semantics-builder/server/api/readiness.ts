import type { Application, Request } from 'express';
import { z } from 'zod';
import type { LakebasePool } from '@databricks/appkit';
import type {
  Assessment,
  ReadinessCheck,
  ReadinessView,
  Recommendation,
  RecommendationStatus,
} from '../../shared/readiness';
import { callTool } from '../llm/llm';
import type { LlmDeps } from '../llm/llm';
import { assessSourcePrompt, assessSourceRequest } from '../llm/prompts/readiness';
import { buildRecommendations, checksFor, inaccessibleChecks, parseDescribe, quoteName } from '../readiness/profile';
import type { NewRecommendation, TableProfile } from '../readiness/profile';
import { StatementRejected } from '../sql/allowlist';
import { runStatement } from '../sql/runner';
import type { RunDeps } from '../sql/runner';
import { projectRepo } from './projects';
import { actorOf, handle, HttpError } from './http';

type Db = Pick<LakebasePool, 'query' | 'connect'>;

interface SourceRow {
  id: string;
  full_name: string;
  role: Assessment['role'];
  report_id: string | null;
  score: number | null;
  checks: ReadinessCheck[] | null;
  assessment: Assessment | null;
  created_at: Date | null;
}

interface RecRow {
  id: string;
  full_name: string | null;
  kind: Recommendation['kind'];
  title: string;
  rationale: string | null;
  statements: string[];
  status: RecommendationStatus;
  error: string | null;
  decided_by: string | null;
  decided_at: Date | null;
}

export interface SourceResult {
  sourceId: string;
  role: Assessment['role'];
  checks: ReadinessCheck[];
  assessment: Assessment | null;
  model: string | null;
  recommendations: NewRecommendation[];
}

export const MAX_SOURCES = 25;

export function readinessRepo(db: Db) {
  return {
    async view(projectId: string): Promise<ReadinessView> {
      const [sources, recs] = await Promise.all([
        db.query<SourceRow>(
          `SELECT s.id, s.full_name, s.role, r.id AS report_id, r.score, r.checks, r.assessment, r.created_at
           FROM gsb.source s
           LEFT JOIN LATERAL (
             SELECT * FROM gsb.readiness_report WHERE source_id = s.id ORDER BY created_at DESC LIMIT 1
           ) r ON true
           WHERE s.project_id = $1 ORDER BY s.full_name`,
          [projectId]
        ),
        db.query<RecRow>(
          `SELECT r.id, s.full_name, r.kind, r.title, r.rationale, r.statements, r.status, r.error, r.decided_by, r.decided_at
           FROM gsb.recommendation r LEFT JOIN gsb.source s ON s.id = r.source_id
           WHERE r.project_id = $1
           ORDER BY array_position(ARRAY['table_comment', 'column_comments', 'primary_key', 'foreign_key'], r.kind),
                    s.full_name, r.created_at`,
          [projectId]
        ),
      ]);
      return {
        sources: sources.rows.map((r) => ({
          sourceId: r.id,
          fullName: r.full_name,
          role: r.role,
          report: r.report_id
            ? {
                id: r.report_id,
                score: r.score,
                checks: r.checks ?? [],
                assessment: r.assessment,
                createdAt: r.created_at!.toISOString(),
              }
            : null,
        })),
        recommendations: recs.rows.map((r) => ({
          id: r.id,
          sourceName: r.full_name,
          kind: r.kind,
          title: r.title,
          rationale: r.rationale ?? '',
          statements: r.statements,
          status: r.status,
          error: r.error,
          decidedBy: r.decided_by,
          decidedAt: r.decided_at?.toISOString() ?? null,
        })),
      };
    },

    /** Replaces open fixes with the new assessment. Applied and rejected fixes stay as history. */
    async saveAssessment(actor: string, projectId: string, results: SourceResult[]): Promise<void> {
      const client = await db.connect();
      try {
        await client.query('BEGIN');
        await client.query(
          `DELETE FROM gsb.recommendation WHERE project_id = $1 AND status IN ('proposed', 'failed')`,
          [projectId]
        );
        let count = 0;
        for (const r of results) {
          const { rows } = await client.query<{ id: string }>(
            `INSERT INTO gsb.readiness_report (project_id, source_id, score, checks, assessment, model, created_by)
             VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id`,
            [projectId, r.sourceId, r.assessment?.score ?? null, JSON.stringify(r.checks), r.assessment, r.model, actor]
          );
          await client.query('UPDATE gsb.source SET role = $2 WHERE id = $1', [r.sourceId, r.role]);
          for (const rec of r.recommendations) {
            await client.query(
              `INSERT INTO gsb.recommendation (project_id, readiness_report_id, source_id, kind, title, rationale, statements)
               VALUES ($1, $2, $3, $4, $5, $6, $7)`,
              [projectId, rows[0].id, r.sourceId, rec.kind, rec.title, rec.rationale, rec.statements]
            );
            count++;
          }
        }
        await client.query(
          `INSERT INTO gsb.audit_log (actor, action, project_id, outcome, detail) VALUES ($1, 'assess_sources', $2, 'succeeded', $3)`,
          [actor, projectId, { sources: results.length, recommendations: count }]
        );
        await client.query('COMMIT');
      } catch (err) {
        await client.query('ROLLBACK');
        throw err;
      } finally {
        client.release();
      }
    },

    /**
     * Moves an open fix to approved only if the statements match what the user saw.
     * The status check makes a double click or a second tab a no-op.
     */
    async claim(actor: string, projectId: string, id: string, statements: string[]): Promise<void> {
      const { rows } = await db.query(
        `UPDATE gsb.recommendation SET status = 'approved', decided_by = $3, decided_at = now(), error = NULL
         WHERE id = $1 AND project_id = $2 AND status IN ('proposed', 'failed') AND statements = $4::text[]
         RETURNING id`,
        [id, projectId, actor, statements]
      );
      if (!rows[0]) throw new HttpError(409, 'This fix changed or was already handled. Reload the page.');
    },

    async finish(id: string, status: 'applied' | 'failed', error: string | null): Promise<void> {
      await db.query(
        `UPDATE gsb.recommendation SET status = $2, error = $3, applied_at = CASE WHEN $2 = 'applied' THEN now() END
         WHERE id = $1`,
        [id, status, error]
      );
    },

    async reject(actor: string, projectId: string, id: string): Promise<void> {
      const { rows } = await db.query(
        `UPDATE gsb.recommendation SET status = 'rejected', decided_by = $3, decided_at = now()
         WHERE id = $1 AND project_id = $2 AND status IN ('proposed', 'failed') RETURNING id`,
        [id, projectId, actor]
      );
      if (!rows[0]) throw new HttpError(409, 'This fix changed or was already handled. Reload the page.');
      await db.query(
        `INSERT INTO gsb.audit_log (actor, action, project_id, target, outcome) VALUES ($1, 'reject_recommendation', $2, $3, 'succeeded')`,
        [actor, projectId, id]
      );
    },
  };
}

/** Profiles each source as the user. A table the user cannot read returns its error instead of a profile. */
export function describeSources<S extends { fullName: string }>(
  sources: S[],
  ctx: { actor: string; projectId: string },
  run: RunDeps
): Promise<{ source: S; profile?: TableProfile; error?: string }[]> {
  return Promise.all(
    sources.map(async (source) => {
      try {
        const res = await runStatement(
          `DESCRIBE TABLE EXTENDED ${quoteName(source.fullName)}`,
          { ...ctx, approved: false },
          run
        );
        return { source, profile: parseDescribe(source.fullName, res.rows) };
      } catch (err) {
        if (err instanceof StatementRejected) throw err;
        return { source, error: (err as Error).message };
      }
    })
  );
}

const idParam = z.object({ id: z.uuid() });
const recParam = idParam.extend({ recId: z.uuid() });
const applyBody = z.object({ statements: z.array(z.string().min(1).max(200_000)).min(1).max(200) });

export function registerReadinessRoutes(
  app: Application,
  db: Db,
  llmFor: (req: Request) => LlmDeps,
  runFor: (req: Request) => RunDeps
) {
  const projects = projectRepo(db);
  const repo = readinessRepo(db);

  app.get(
    '/api/projects/:id/readiness',
    handle(async (req) => {
      const project = await projects.get(actorOf(req), idParam.parse(req.params).id);
      return repo.view(project.id);
    })
  );

  app.post(
    '/api/projects/:id/readiness/run',
    handle(async (req) => {
      const actor = actorOf(req);
      const project = await projects.get(actor, idParam.parse(req.params).id);
      const brief = await projects.latestBrief(project.id);
      if (brief?.status !== 'confirmed')
        throw new HttpError(409, 'Confirm the Semantic Brief before you assess sources.');
      const { sources } = await repo.view(project.id);
      if (!sources.length) throw new HttpError(409, 'The confirmed brief has no candidate sources.');
      if (sources.length > MAX_SOURCES) throw new HttpError(400, `Assess at most ${MAX_SOURCES} sources at a time.`);

      const described = await describeSources(sources, { actor, projectId: project.id }, runFor(req));
      const profiles = described.flatMap((d) => (d.profile ? [d.profile] : []));

      const llm = llmFor(req);
      const results = await Promise.all(
        described.map(async ({ source, profile, error }): Promise<SourceResult> => {
          if (!profile) {
            return {
              sourceId: source.sourceId,
              role: source.role,
              checks: inaccessibleChecks(error ?? ''),
              assessment: null,
              model: null,
              recommendations: [],
            };
          }
          const checks = checksFor(profile);
          const others = profiles.filter((p) => p !== profile);
          const out = await callTool(
            assessSourcePrompt,
            assessSourceRequest(brief.brief, profile, checks, others),
            llm
          );
          const byName = new Map<string, TableProfile>(others.map((o) => [o.fullName.toLowerCase(), o]));
          return {
            sourceId: source.sourceId,
            role: out.role,
            checks,
            assessment: { role: out.role, score: out.score, summary: out.summary, findings: out.findings },
            model: llm.endpoint ?? null,
            recommendations: buildRecommendations(profile, out, byName),
          };
        })
      );
      await repo.saveAssessment(actor, project.id, results);
      return repo.view(project.id);
    })
  );

  app.post(
    '/api/projects/:id/recommendations/:recId/apply',
    handle(async (req) => {
      const actor = actorOf(req);
      const { id, recId } = recParam.parse(req.params);
      const project = await projects.get(actor, id);
      const { statements } = applyBody.parse(req.body);
      await repo.claim(actor, project.id, recId, statements);

      const run = runFor(req);
      for (const [i, statement] of statements.entries()) {
        try {
          await runStatement(statement, { actor, projectId: project.id, approved: true }, run);
        } catch (err) {
          const reason = (err as Error).message.slice(0, 500);
          await repo.finish(recId, 'failed', `Statement ${i + 1} of ${statements.length} failed: ${reason}`);
          return repo.view(project.id);
        }
      }
      await repo.finish(recId, 'applied', null);
      return repo.view(project.id);
    })
  );

  app.post(
    '/api/projects/:id/recommendations/:recId/reject',
    handle(async (req) => {
      const actor = actorOf(req);
      const { id, recId } = recParam.parse(req.params);
      const project = await projects.get(actor, id);
      await repo.reject(actor, project.id, recId);
      return repo.view(project.id);
    })
  );
}
