import type { Application, Request } from 'express';
import type { LakebasePool } from '@databricks/appkit';
import type { AdoptableView, LibraryRow } from '../../shared/promote';
import { sandboxSchema } from '../designer/validate';
import { runStatement } from '../sql/runner';
import type { RunDeps } from '../sql/runner';
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
  check_at: Date | null;
  check_errors: number | null;
  check_warnings: number | null;
}

/** Every sub-project of the user with a design: its Unity Catalog view, promoted and latest versions. */
const MAX_ADOPTABLE = 1000;

export function registerLibraryRoutes(app: Application, db: Db, runFor: (req: Request) => RunDeps) {
  /**
   * Every metric view the user can see in Unity Catalog that the app does not manage for them: one read of
   * information_schema, as the user, so it lists only what their privileges allow. Sandbox copies are left out.
   */
  app.get(
    '/api/library/adoptable',
    handle(async (req): Promise<AdoptableView[]> => {
      const actor = actorOf(req);
      const res = await runStatement(
        `SELECT table_catalog, table_schema, table_name, table_owner, CAST(last_altered AS STRING), comment
         FROM system.information_schema.tables WHERE table_type = 'METRIC_VIEW'
         ORDER BY last_altered DESC LIMIT ${MAX_ADOPTABLE}`,
        { actor, approved: false },
        runFor(req)
      );
      const { rows: managed } = await db.query<{ target: string; mine: boolean }>(
        `SELECT lower(promotion_target) AS target, bool_or(created_by = $1) AS mine
         FROM gsb.project WHERE promotion_target IS NOT NULL GROUP BY lower(promotion_target)`,
        [actor]
      );
      const byTarget = new Map(managed.map((m) => [m.target, m.mine]));
      const sandbox = sandboxSchema()?.toLowerCase();
      return res.rows.flatMap((r) => {
        const fullName = [r[0], r[1], r[2]].join('.');
        const key = fullName.toLowerCase();
        if (sandbox && `${r[0]}.${r[1]}`.toLowerCase() === sandbox) return [];
        if (byTarget.get(key) === true) return [];
        return [
          {
            fullName,
            owner: r[3] ?? null,
            lastAltered: r[4] ?? null,
            comment: r[5] ?? null,
            managedByOther: byTarget.get(key) === false,
          },
        ];
      });
    })
  );

  app.get(
    '/api/library',
    handle(async (req): Promise<LibraryRow[]> => {
      const { rows } = await db.query<Row>(
        `SELECT s.id, s.parent_id, p.name AS project, s.name AS sub, d.name, s.promotion_target,
           d.version AS latest_version, d.status AS latest_status,
           pr.version AS promoted_version, pr.created_by AS promoted_by, pr.created_at AS promoted_at,
           (SELECT r.sandbox_view FROM gsb.validation_run r JOIN gsb.metric_view_draft x ON x.id = r.draft_id
            WHERE x.project_id = s.id AND r.status = 'passed' ORDER BY r.created_at DESC LIMIT 1) AS sandbox_view,
           dc.created_at AS check_at,
           (SELECT count(*)::int FROM jsonb_array_elements(dc.findings) f WHERE f->>'severity' = 'error') AS check_errors,
           (SELECT count(*)::int FROM jsonb_array_elements(dc.findings) f WHERE f->>'severity' = 'warning') AS check_warnings
         FROM gsb.project s
         JOIN gsb.project p ON p.id = s.parent_id
         JOIN LATERAL (SELECT version, status, name FROM gsb.metric_view_draft
                       WHERE project_id = s.id ORDER BY version DESC LIMIT 1) d ON true
         LEFT JOIN LATERAL (SELECT version, created_by, created_at FROM gsb.promotion
                            WHERE project_id = s.id AND status = 'succeeded' ORDER BY created_at DESC LIMIT 1) pr ON true
         LEFT JOIN LATERAL (SELECT created_at, findings FROM gsb.drift_check
                            WHERE project_id = s.id ORDER BY created_at DESC LIMIT 1) dc ON true
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
        health: r.check_at
          ? {
              status: r.check_errors ? 'error' : r.check_warnings ? 'warning' : 'ok',
              at: r.check_at.toISOString(),
            }
          : null,
      }));
    })
  );
}
