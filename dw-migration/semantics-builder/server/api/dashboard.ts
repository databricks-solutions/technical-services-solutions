import type { Application, Request } from 'express';
import { z } from 'zod';
import { getWarehouseId } from '@databricks/appkit';
import type { LakebasePool } from '@databricks/appkit';
import type { DashboardView } from '../../shared/dashboard';
import { validateMetricView } from '../../shared/metricView';
import { starterDashboard } from '../dashboard/build';
import type { UcDeps } from '../uc/metadata';
import { designerRepo } from './designer';
import { actorOf, handle, HttpError } from './http';
import { projectRepo } from './projects';

type Db = Pick<LakebasePool, 'query' | 'connect'>;
const idParam = z.object({ id: z.uuid() });

/**
 * A starter AI/BI dashboard on the promoted view of a sub-project: KPIs, a monthly trend and a breakdown, all from
 * the governed measures. Apps cannot get the scope of the dashboards API, so the app shows the dashboard JSON and
 * the `databricks lakeview create` command, and the user runs it as themselves.
 */
export function registerDashboardRoutes(app: Application, db: Db, ucFor: (req: Request) => UcDeps) {
  const projects = projectRepo(db);
  const designs = designerRepo(db);

  app.get(
    '/api/projects/:id/dashboard',
    handle(async (req): Promise<DashboardView> => {
      const actor = actorOf(req);
      const project = await projects.get(actor, idParam.parse(req.params).id);
      if (!project.parentId) throw new HttpError(400, 'Dashboards are on sub-projects.');
      const { rows } = await db.query<{ version: number; target: string }>(
        `SELECT pr.version, pr.target FROM gsb.promotion pr JOIN gsb.project p ON p.id = pr.project_id
         WHERE pr.project_id = $1 AND pr.status = 'succeeded' AND pr.target = p.promotion_target
         ORDER BY pr.created_at DESC LIMIT 1`,
        [project.id]
      );
      const p = rows[0];
      let plan: DashboardView['plan'] = null;
      if (p) {
        const mv = validateMetricView((await designs.view(project.id, p.version)).draft!.yaml).view;
        const { columns = [] } = await ucFor(req).table(p.target);
        const types = new Map(columns.map((c) => [c.name ?? '', c.type_text ?? '']));
        if (mv) plan = starterDashboard(project.name, p.target, mv, types);
      }
      return {
        promoted: p ? { view: p.target, version: p.version } : null,
        plan,
        folder: `/Users/${actor}`,
        name: `${project.name} - starter`,
        warehouseId: (await getWarehouseId().catch(() => null)) ?? null,
      };
    })
  );
}
