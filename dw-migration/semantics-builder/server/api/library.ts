import type { Application } from 'express';
import type { LakebasePool } from '@databricks/appkit';
import type { LibraryRow } from '../../shared/promote';
import { actorOf, handle } from './http';

type Db = Pick<LakebasePool, 'query'>;

interface Row {
  id: string;
  parent_id: string;
  project: string;
  sub: string;
  name: string;
  promotion_target: string | null;
  latest_version: number;
  latest_status: 'draft' | 'validated';
  promoted_version: number | null;
  promoted_by: string | null;
  promoted_at: Date | null;
  sandbox_view: string | null;
}

/** Every sub-project of the user with a design: its Unity Catalog view, promoted and latest versions. */
export function registerLibraryRoutes(app: Application, db: Db) {
  app.get(
    '/api/library',
    handle(async (req): Promise<LibraryRow[]> => {
      const { rows } = await db.query<Row>(
        `SELECT s.id, s.parent_id, p.name AS project, s.name AS sub, d.name, s.promotion_target,
           d.version AS latest_version, d.status AS latest_status,
           pr.version AS promoted_version, pr.created_by AS promoted_by, pr.created_at AS promoted_at,
           (SELECT r.sandbox_view FROM gsb.validation_run r JOIN gsb.metric_view_draft x ON x.id = r.draft_id
            WHERE x.project_id = s.id AND r.status = 'passed' ORDER BY r.created_at DESC LIMIT 1) AS sandbox_view
         FROM gsb.project s
         JOIN gsb.project p ON p.id = s.parent_id
         JOIN LATERAL (SELECT version, status, name FROM gsb.metric_view_draft
                       WHERE project_id = s.id ORDER BY version DESC LIMIT 1) d ON true
         LEFT JOIN LATERAL (SELECT version, created_by, created_at FROM gsb.promotion
                            WHERE project_id = s.id AND status = 'succeeded' ORDER BY created_at DESC LIMIT 1) pr ON true
         WHERE s.created_by = $1
         ORDER BY p.name, s.name
         LIMIT 500`,
        [actorOf(req)]
      );
      return rows.map((r) => ({
        projectId: r.id,
        parentId: r.parent_id,
        project: r.project,
        subProject: r.sub,
        name: r.name,
        target: r.promotion_target,
        latest: { version: r.latest_version, status: r.latest_status },
        promoted:
          r.promoted_version !== null && r.promoted_by && r.promoted_at
            ? { version: r.promoted_version, by: r.promoted_by, at: r.promoted_at.toISOString() }
            : null,
        sandboxView: r.sandbox_view,
      }));
    })
  );
}
