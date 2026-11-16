import type { Application, Request } from 'express';
import { z } from 'zod';
import type { LakebasePool } from '@databricks/appkit';
import type { AccessResult, AccessRun, AccessView } from '../../shared/access';
import { runAccessCheck } from '../designer/access';
import type { RunDeps } from '../sql/runner';
import { designerRepo } from './designer';
import { actorOf, handle, HttpError } from './http';
import { projectRepo } from './projects';
import { reviewRepo } from './review';

type Db = Pick<LakebasePool, 'query' | 'connect'>;
const idParam = z.object({ id: z.uuid() });

/**
 * The tests of the promoted view, run as the owner and as a reviewer with less access (row filters, column masks,
 * grants). The app cannot act as another person, so each person runs the check as themselves.
 */
export function registerAccessRoutes(app: Application, db: Db, runFor: (req: Request) => RunDeps) {
  const projects = projectRepo(db);
  const designs = designerRepo(db);
  const reviews = reviewRepo(db);

  async function promoted(projectId: string) {
    const { rows } = await db.query<{ version: number; target: string; owner: string }>(
      `SELECT pr.version, pr.target, p.created_by AS owner FROM gsb.promotion pr JOIN gsb.project p ON p.id = pr.project_id
       WHERE pr.project_id = $1 AND pr.status = 'succeeded' AND pr.target = p.promotion_target
       ORDER BY pr.created_at DESC LIMIT 1`,
      [projectId]
    );
    return rows[0] ?? null;
  }

  async function view(projectId: string, only?: string): Promise<AccessView> {
    const p = await promoted(projectId);
    if (!p) return { target: null, version: null, tests: 0, runs: [], problem: 'Promote a version first.' };
    const tests = (await designs.view(projectId, p.version)).draft!.tests.length;
    const { rows } = await db.query<{ run_by: string; results: AccessResult[]; created_at: Date }>(
      `SELECT DISTINCT ON (lower(run_by)) run_by, results, created_at FROM gsb.access_check
       WHERE project_id = $1 AND version = $2 AND target = $3 AND ($4::text IS NULL OR lower(run_by) = lower($4))
       ORDER BY lower(run_by), created_at DESC`,
      [projectId, p.version, p.target, only ?? null]
    );
    const runs: AccessRun[] = rows
      .map((r) => ({
        runBy: r.run_by,
        isOwner: r.run_by.toLowerCase() === p.owner.toLowerCase(),
        version: p.version,
        results: r.results,
        createdAt: r.created_at.toISOString(),
      }))
      .sort((a, b) => Number(b.isOwner) - Number(a.isOwner));
    return {
      target: p.target,
      version: p.version,
      tests,
      runs,
      problem: tests ? null : `Version ${p.version} has no tests. Add tests, then promote again.`,
    };
  }

  async function check(req: Request, actor: string, projectId: string) {
    const p = await promoted(projectId);
    if (!p) throw new HttpError(409, 'Promote a version first.');
    const tests = (await designs.view(projectId, p.version)).draft!.tests;
    if (!tests.length) throw new HttpError(409, `Version ${p.version} has no tests.`);
    const results = await runAccessCheck(p.target, tests, { actor, projectId }, runFor(req));
    await db.query(
      `INSERT INTO gsb.access_check (project_id, version, target, run_by, results) VALUES ($1, $2, $3, $4, $5)`,
      [projectId, p.version, p.target, actor, JSON.stringify(results)]
    );
  }

  app.get(
    '/api/projects/:id/access',
    handle(async (req) => view((await projects.get(actorOf(req), idParam.parse(req.params).id)).id))
  );

  app.post(
    '/api/projects/:id/access',
    handle(async (req) => {
      const actor = actorOf(req);
      const project = await projects.get(actor, idParam.parse(req.params).id);
      await check(req, actor, project.id);
      return view(project.id);
    })
  );

  /** For the reviewer: only their own run. */
  app.get(
    '/api/reviews/:id/access',
    handle(async (req) => {
      const actor = actorOf(req);
      const review = await reviews.get(actor, idParam.parse(req.params).id);
      return view(review.projectId, actor);
    })
  );

  app.post(
    '/api/reviews/:id/access',
    handle(async (req) => {
      const actor = actorOf(req);
      const review = await reviews.get(actor, idParam.parse(req.params).id);
      if (review.reviewer.toLowerCase() !== actor.toLowerCase())
        throw new HttpError(403, 'Only the reviewer runs this check from a review.');
      await check(req, actor, review.projectId);
      return view(review.projectId, actor);
    })
  );
}
