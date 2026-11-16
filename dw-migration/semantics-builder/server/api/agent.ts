import { createHash } from 'node:crypto';
import type { Application, Request } from 'express';
import { z } from 'zod';
import type { LakebasePool } from '@databricks/appkit';
import { accessBody, accessCommand, agentBody } from '../../shared/agent';
import type { AgentCandidate, AgentView, GoldenView } from '../../shared/agent';
import type { TuningChange } from '../../shared/genie';
import { validateMetricView } from '../../shared/metricView';
import type { GenieDeps } from '../genie/client';
import { golden } from '../genie/golden';
import type { SubFacts } from '../genie/golden';
import { agentConfig } from '../genie/space';
import type { RunDeps } from '../sql/runner';
import { readStatus } from './certify';
import type { AgentPart } from '../genie/space';
import type { UcDeps } from '../uc/metadata';
import { designerRepo } from './designer';
import { actorOf, handle, HttpError } from './http';
import { projectRepo } from './projects';

type Db = Pick<LakebasePool, 'query' | 'connect'>;
const idParam = z.object({ id: z.uuid() });
const hashOf = (config: string) => createHash('sha256').update(config).digest('hex');
const sameSet = (a: string[], b: string[]) => a.length === b.length && [...a].sort().join() === [...b].sort().join();

/**
 * The production Genie agent of a top-level project: one Genie space on the promoted views of the sub-projects that
 * the author chooses, so related sub-projects answer together. Each view brings the settings of its promoted version
 * and the changes kept by Optimize with benchmarks. The author creates it after examining the settings, and runs the
 * command that gives CAN RUN to the audience.
 */
export function registerAgentRoutes(
  app: Application,
  db: Db,
  genieFor: (req: Request) => GenieDeps,
  ucFor: (req: Request) => UcDeps,
  runFor: (req: Request) => RunDeps
) {
  const projects = projectRepo(db);
  const designs = designerRepo(db);

  async function context(req: Request) {
    const actor = actorOf(req);
    const project = await projects.get(actor, idParam.parse(req.params).id);
    if (project.parentId) throw new HttpError(400, 'The Genie agent is on the main project.');
    const [subs, agent] = await Promise.all([
      db.query<{ id: string; name: string; target: string; version: number; kept: number }>(
        `SELECT s.id, s.name, pr.target, pr.version,
           (SELECT count(*)::int FROM gsb.genie_tuning t WHERE t.project_id = s.id AND t.status = 'kept') AS kept
         FROM gsb.project s
         JOIN LATERAL (
           SELECT target, version FROM gsb.promotion
           WHERE project_id = s.id AND status = 'succeeded' AND target = s.promotion_target
           ORDER BY created_at DESC LIMIT 1
         ) pr ON true
         WHERE s.parent_id = $1 ORDER BY s.name`,
        [project.id]
      ),
      db.query<{ space_id: string; sub_projects: string[]; config_hash: string; created_at: Date; updated_at: Date }>(
        'SELECT space_id, sub_projects, config_hash, created_at, updated_at FROM gsb.genie_agent WHERE project_id = $1',
        [project.id]
      ),
    ]);
    const candidates: AgentCandidate[] = subs.rows.map((r) => ({
      projectId: r.id,
      name: r.name,
      view: r.target,
      version: r.version,
      kept: r.kept,
    }));
    return { actor, project, candidates, agent: agent.rows[0] ?? null };
  }
  type Ctx = Awaited<ReturnType<typeof context>>;

  /** One part for each chosen sub-project. Text dimensions come from the promoted view, read as the user. */
  async function configOf(req: Request, ctx: Ctx, subProjects: string[]) {
    const chosen = ctx.candidates.filter((c) => subProjects.includes(c.projectId));
    if (chosen.length !== new Set(subProjects).size)
      throw new HttpError(409, 'Choose sub-projects of this project that have a promoted view.');
    const uc = ucFor(req);
    const parts: AgentPart[] = await Promise.all(
      chosen.map(async (c) => {
        const draft = (await designs.view(c.projectId, c.version)).draft!;
        const dims = new Set((validateMetricView(draft.yaml).view?.dimensions ?? []).map((d) => d.name));
        const textDimensions = await uc.table(c.view).then(
          ({ columns = [] }) =>
            columns
              .filter((col) => col.name && dims.has(col.name) && /^(string|varchar|char)/i.test(col.type_text ?? ''))
              .map((col) => col.name!),
          () => []
        );
        const kept = (
          await db.query<{ change: TuningChange }>(
            `SELECT change FROM gsb.genie_tuning WHERE project_id = $1 AND status = 'kept' ORDER BY created_at`,
            [c.projectId]
          )
        ).rows.map((r) => r.change);
        const brief = (await projects.latestBrief(c.projectId))?.brief ?? null;
        return { name: c.name, view: c.view, brief, tests: draft.tests, textDimensions, kept };
      })
    );
    return JSON.stringify(agentConfig(parts), null, 2);
  }

  async function view(req: Request, ctx?: Ctx): Promise<AgentView> {
    const c = ctx ?? (await context(req));
    let current = false;
    if (c.agent)
      try {
        current = c.agent.config_hash === hashOf(await configOf(req, c, c.agent.sub_projects));
      } catch {
        // A chosen sub-project has no promoted view any more.
      }
    return {
      candidates: c.candidates,
      agent: c.agent
        ? {
            spaceId: c.agent.space_id,
            subProjects: c.agent.sub_projects,
            createdAt: c.agent.created_at.toISOString(),
            updatedAt: c.agent.updated_at.toISOString(),
            current,
          }
        : null,
    };
  }

  const audit = (actor: string, action: string, projectId: string, target: string, detail?: unknown) =>
    db.query(
      `INSERT INTO gsb.audit_log (actor, action, project_id, target, outcome, detail) VALUES ($1, $2, $3, $4, 'succeeded', $5)`,
      [actor, action, projectId, target, detail ?? null]
    );

  app.get(
    '/api/projects/:id/agent',
    handle((req) => view(req))
  );

  /**
   * Without `config`, returns the settings for the chosen sub-projects, to examine. With it, creates the agent, or
   * replaces all its settings, only if they are the same.
   */
  app.post(
    '/api/projects/:id/agent',
    handle(async (req) => {
      const { subProjects, config } = agentBody.parse(req.body);
      const ctx = await context(req);
      const settings = await configOf(req, ctx, subProjects);
      if (config === undefined) return { config: settings };
      if (config !== settings)
        throw new HttpError(409, 'The settings changed since you examined them. Examine them again.');
      const genie = genieFor(req);
      const views = ctx.candidates.filter((c) => subProjects.includes(c.projectId)).map((c) => c.view);
      if (ctx.agent) {
        await genie.updateSpace(ctx.agent.space_id, config);
        await db.query(
          `UPDATE gsb.genie_agent SET sub_projects = $2, config_hash = $3, updated_at = now() WHERE project_id = $1`,
          [ctx.project.id, subProjects, hashOf(config)]
        );
        await audit(ctx.actor, 'update_genie_agent', ctx.project.id, ctx.agent.space_id, {
          views,
          changedViews: !sameSet(ctx.agent.sub_projects, subProjects),
        });
      } else {
        const spaceId = await genie.createSpace(
          ctx.project.name,
          (ctx.project.description ?? '').slice(0, 1000),
          config
        );
        await db.query(
          `INSERT INTO gsb.genie_agent (project_id, space_id, sub_projects, config_hash, created_by)
           VALUES ($1, $2, $3, $4, $5)`,
          [ctx.project.id, spaceId, subProjects, hashOf(config), ctx.actor]
        );
        await audit(ctx.actor, 'create_genie_agent', ctx.project.id, spaceId, { views });
      }
      return view(req);
    })
  );

  /** The command that gives CAN RUN to the audience. The author runs it; the app cannot change permissions. */
  app.post(
    '/api/projects/:id/agent/access',
    handle(async (req) => {
      const { principals } = accessBody.parse(req.body);
      const ctx = await context(req);
      if (!ctx.agent) throw new HttpError(409, 'Create the Genie agent first.');
      return { command: accessCommand(ctx.agent.space_id, principals) };
    })
  );

  /**
   * The golden project gates: for each sub-project in the agent (or each promoted one, before the agent exists),
   * certified tables, an approved promoted version and Genie accuracy; and an up-to-date agent. Tags are read as the
   * user.
   */
  app.get(
    '/api/projects/:id/golden',
    handle(async (req): Promise<GoldenView> => {
      const ctx = await context(req);
      const agent = await view(req, ctx);
      const ids = ctx.agent?.sub_projects ?? ctx.candidates.map((c) => c.projectId);
      const run = runFor(req);
      const facts: SubFacts[] = await Promise.all(
        ctx.candidates
          .filter((c) => ids.includes(c.projectId))
          .map(async (c) => {
            const [tables, approved, last] = await Promise.all([
              db.query<{ full_name: string }>('SELECT full_name FROM gsb.source WHERE project_id = $1', [c.projectId]),
              db.query<{ ok: boolean }>(
                `SELECT EXISTS (SELECT 1 FROM gsb.review WHERE project_id = $1 AND kind = 'view' AND version = $2
                   AND status = 'approved') AS ok`,
                [c.projectId, c.version]
              ),
              db.query<{ num_correct: number; num_questions: number; finished_at: Date }>(
                `SELECT num_correct, num_questions, finished_at FROM gsb.genie_eval
                 WHERE project_id = $1 AND status = 'done' AND version = $2 ORDER BY created_at DESC LIMIT 1`,
                [c.projectId, c.version]
              ),
            ]);
            const names = tables.rows.map((t) => t.full_name);
            const status = names.length
              ? await readStatus(names, ctx.actor, run).catch(() => new Map<string, string>())
              : new Map<string, string>();
            const r = last.rows[0];
            return {
              projectId: c.projectId,
              name: c.name,
              view: c.view,
              version: c.version,
              tables: names.length,
              certified: names.filter((n) => status.get(n.toLowerCase()) === 'certified').length,
              approved: approved.rows[0]?.ok ?? false,
              run: r ? { correct: r.num_correct, questions: r.num_questions, at: r.finished_at.toISOString() } : null,
            };
          })
      );
      return golden(agent.agent ? { exists: true, current: agent.agent.current } : null, facts);
    })
  );
}
