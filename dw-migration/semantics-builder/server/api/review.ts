import type { Application, Request } from 'express';
import { z } from 'zod';
import type { LakebasePool } from '@databricks/appkit';
import { approvalSchema, decisionSchema, requestReviewSchema } from '../../shared/review';
import type { ApprovalState, Review, ReviewDetail, ReviewList } from '../../shared/review';
import { readImpact } from '../designer/impact';
import { createStatement } from '../designer/validate';
import type { RunDeps } from '../sql/runner';
import type { UcDeps } from '../uc/metadata';
import { designerRepo } from './designer';
import { actorOf, handle, HttpError } from './http';
import { projectRepo } from './projects';

type Db = Pick<LakebasePool, 'query' | 'connect'>;
const idParam = z.object({ id: z.uuid() });

interface ReviewRow {
  id: string;
  project_id: string;
  parent_id: string;
  project: string;
  sub_project: string;
  version: number;
  target: string | null;
  reviewer: string;
  requested_by: string;
  request_comment: string | null;
  status: Review['status'];
  decision_comment: string | null;
  decided_at: Date | null;
  created_at: Date;
}

const SELECT = `
  SELECT r.id, r.project_id, s.parent_id, p.name AS project, s.name AS sub_project, r.version,
         s.promotion_target AS target, r.reviewer, r.requested_by, r.request_comment, r.status,
         r.decision_comment, r.decided_at, r.created_at
  FROM gsb.review r JOIN gsb.project s ON s.id = r.project_id JOIN gsb.project p ON p.id = s.parent_id`;

const toReview = (r: ReviewRow): Review => ({
  id: r.id,
  projectId: r.project_id,
  parentId: r.parent_id,
  project: r.project,
  subProject: r.sub_project,
  version: r.version,
  target: r.target,
  reviewer: r.reviewer,
  requestedBy: r.requested_by,
  requestComment: r.request_comment,
  status: r.status,
  decisionComment: r.decision_comment,
  decidedAt: r.decided_at?.toISOString() ?? null,
  createdAt: r.created_at.toISOString(),
});

const same = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase();

export function reviewRepo(db: Db) {
  return {
    async state(projectId: string): Promise<ApprovalState> {
      const [flag, latest] = await Promise.all([
        db.query<{ require_approval: boolean }>('SELECT require_approval FROM gsb.project WHERE id = $1', [projectId]),
        db.query<ReviewRow>(`${SELECT} WHERE r.project_id = $1 ORDER BY r.created_at DESC LIMIT 1`, [projectId]),
      ]);
      return {
        required: flag.rows[0]?.require_approval ?? false,
        review: latest.rows[0] ? toReview(latest.rows[0]) : null,
      };
    },

    /** Why Promote of this version is blocked by the approval rule, or null. */
    async gate(projectId: string, version: number): Promise<string | null> {
      const { rows } = await db.query<{ ok: boolean }>(
        `SELECT NOT p.require_approval OR EXISTS (
           SELECT 1 FROM gsb.review r WHERE r.project_id = p.id AND r.version = $2 AND r.status = 'approved') AS ok
         FROM gsb.project p WHERE p.id = $1`,
        [projectId, version]
      );
      return rows[0]?.ok === false ? `Version ${version} needs approval by a reviewer before Promote.` : null;
    },

    /** The review, when the actor is its reviewer or its author. */
    async get(actor: string, id: string): Promise<Review> {
      const { rows } = await db.query<ReviewRow>(
        `${SELECT} WHERE r.id = $1 AND (lower(r.reviewer) = lower($2) OR lower(r.requested_by) = lower($2))`,
        [id, actor]
      );
      if (!rows[0]) throw new HttpError(404, 'Review not found.');
      return toReview(rows[0]);
    },
  };
}

/**
 * Approval before Promote. The author of a sub-project names one reviewer by email. The reviewer sees that version
 * read-only (YAML, tests, impact) and approves or rejects it. Every step goes to the audit log.
 */
export function registerReviewRoutes(
  app: Application,
  db: Db,
  runFor: (req: Request) => RunDeps,
  ucFor: (req: Request) => UcDeps
) {
  const projects = projectRepo(db);
  const designs = designerRepo(db);
  const reviews = reviewRepo(db);

  async function owned(req: Request) {
    const actor = actorOf(req);
    const project = await projects.get(actor, idParam.parse(req.params).id);
    if (!project.parentId) throw new HttpError(400, 'Approvals are on sub-projects.');
    return { actor, project };
  }

  const audit = (actor: string, action: string, projectId: string, target: string, detail?: unknown) =>
    db.query(
      `INSERT INTO gsb.audit_log (actor, action, project_id, target, outcome, detail)
       VALUES ($1, $2, $3, $4, 'succeeded', $5)`,
      [actor, action, projectId, target, detail ?? null]
    );

  app.get(
    '/api/projects/:id/approval',
    handle(async (req) => reviews.state((await owned(req)).project.id))
  );

  app.post(
    '/api/projects/:id/approval',
    handle(async (req): Promise<ApprovalState> => {
      const { required } = approvalSchema.parse(req.body);
      const { actor, project } = await owned(req);
      await db.query('UPDATE gsb.project SET require_approval = $2 WHERE id = $1', [project.id, required]);
      await audit(actor, required ? 'require_approval' : 'drop_approval', project.id, project.id);
      return reviews.state(project.id);
    })
  );

  app.post(
    '/api/projects/:id/reviews',
    handle(async (req): Promise<ApprovalState> => {
      const body = requestReviewSchema.parse(req.body);
      const { actor, project } = await owned(req);
      if (same(body.reviewer, actor))
        throw new HttpError(400, 'Name another person. You cannot approve your own version.');
      const draft = (await designs.view(project.id)).draft;
      if (draft?.status !== 'validated')
        throw new HttpError(409, 'Validate the latest version before you ask for approval.');
      const client = await db.connect();
      try {
        await client.query('BEGIN');
        await client.query(
          `UPDATE gsb.review SET status = 'cancelled', decided_at = now() WHERE project_id = $1 AND status = 'pending'`,
          [project.id]
        );
        const { rows } = await client.query<{ id: string }>(
          `INSERT INTO gsb.review (project_id, version, reviewer, requested_by, request_comment)
           VALUES ($1, $2, $3, $4, $5) RETURNING id`,
          [project.id, draft.version, body.reviewer.trim().toLowerCase(), actor, body.comment || null]
        );
        await client.query(
          `INSERT INTO gsb.audit_log (actor, action, project_id, target, outcome, detail)
           VALUES ($1, 'request_review', $2, $3, 'succeeded', $4)`,
          [actor, project.id, rows[0].id, { version: draft.version, reviewer: body.reviewer }]
        );
        await client.query('COMMIT');
      } catch (err) {
        await client.query('ROLLBACK');
        throw err;
      } finally {
        client.release();
      }
      return reviews.state(project.id);
    })
  );

  app.post(
    '/api/projects/:id/reviews/cancel',
    handle(async (req): Promise<ApprovalState> => {
      const { actor, project } = await owned(req);
      const { rows } = await db.query<{ id: string }>(
        `UPDATE gsb.review SET status = 'cancelled', decided_at = now()
         WHERE project_id = $1 AND status = 'pending' RETURNING id`,
        [project.id]
      );
      if (rows[0]) await audit(actor, 'cancel_review', project.id, rows[0].id);
      return reviews.state(project.id);
    })
  );

  app.get(
    '/api/reviews',
    handle(async (req): Promise<ReviewList> => {
      const actor = actorOf(req);
      const [toMe, byMe] = await Promise.all([
        db.query<ReviewRow>(
          `${SELECT} WHERE lower(r.reviewer) = lower($1) AND r.status <> 'cancelled' ORDER BY r.created_at DESC LIMIT 100`,
          [actor]
        ),
        db.query<ReviewRow>(`${SELECT} WHERE lower(r.requested_by) = lower($1) ORDER BY r.created_at DESC LIMIT 100`, [
          actor,
        ]),
      ]);
      return { toMe: toMe.rows.map(toReview), byMe: byMe.rows.map(toReview) };
    })
  );

  app.get(
    '/api/reviews/:id',
    handle(async (req): Promise<ReviewDetail> => {
      const actor = actorOf(req);
      const review = await reviews.get(actor, idParam.parse(req.params).id);
      const view = await designs.view(review.projectId, review.version);
      const draft = view.draft!;
      let ucYaml: string | null = null;
      if (review.target)
        try {
          ucYaml = (await ucFor(req).table(review.target)).view_definition ?? null;
        } catch {
          // Not in UC yet, or the reviewer cannot read it: show the new YAML only.
        }
      return {
        review,
        canDecide: review.status === 'pending' && same(review.reviewer, actor) && !same(review.requestedBy, actor),
        yaml: draft.yaml,
        ucYaml,
        statement: review.target ? createStatement(review.target, draft.yaml) : null,
        tests: draft.tests,
        validation: view.validation,
      };
    })
  );

  app.get(
    '/api/reviews/:id/impact',
    handle(async (req) => {
      const actor = actorOf(req);
      const review = await reviews.get(actor, idParam.parse(req.params).id);
      const draft = (await designs.view(review.projectId, review.version)).draft!;
      return readImpact(
        { actor, projectId: review.projectId, run: runFor(req), uc: ucFor(req) },
        review.target,
        draft.yaml
      );
    })
  );

  app.post(
    '/api/reviews/:id/decision',
    handle(async (req): Promise<Review> => {
      const actor = actorOf(req);
      const { decision, comment } = decisionSchema.parse(req.body);
      const review = await reviews.get(actor, idParam.parse(req.params).id);
      if (!same(review.reviewer, actor) || same(review.requestedBy, actor))
        throw new HttpError(403, 'Only the named reviewer can decide.');
      const { rows } = await db.query<{ id: string }>(
        `UPDATE gsb.review SET status = $2, decision_comment = $3, decided_at = now()
         WHERE id = $1 AND status = 'pending' RETURNING id`,
        [review.id, decision, comment || null]
      );
      if (!rows[0]) throw new HttpError(409, 'This review is not open any more.');
      await audit(actor, decision === 'approved' ? 'approve_review' : 'reject_review', review.projectId, review.id, {
        version: review.version,
      });
      return reviews.get(actor, review.id);
    })
  );
}
