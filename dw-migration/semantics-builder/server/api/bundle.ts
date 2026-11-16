import type { Application } from 'express';
import { z } from 'zod';
import type { LakebasePool } from '@databricks/appkit';
import type { BundleView } from '../../shared/bundle';
import { validateMetricView } from '../../shared/metricView';
import { bundleFiles } from '../bundle/build';
import { writeZip } from '../bundle/zip';
import { designerRepo } from './designer';
import { actorOf, handle, HttpError } from './http';
import { projectRepo } from './projects';

type Db = Pick<LakebasePool, 'query' | 'connect'>;
const idParam = z.object({ id: z.uuid() });

/**
 * A Declarative Automation Bundle of the promoted view of a sub-project, for CI/CD: the files to show, and the same
 * files as a zip. It only reads app metadata; the user deploys it with the CLI or a pipeline, as themselves.
 */
export function registerBundleRoutes(app: Application, db: Db) {
  const projects = projectRepo(db);
  const designs = designerRepo(db);

  app.get(
    '/api/projects/:id/bundle',
    handle(async (req): Promise<BundleView> => {
      const actor = actorOf(req);
      const project = await projects.get(actor, idParam.parse(req.params).id);
      if (!project.parentId) throw new HttpError(400, 'Bundles are on sub-projects.');
      const { rows } = await db.query<{ version: number; target: string }>(
        `SELECT pr.version, pr.target FROM gsb.promotion pr JOIN gsb.project p ON p.id = pr.project_id
         WHERE pr.project_id = $1 AND pr.status = 'succeeded' AND pr.target = p.promotion_target
         ORDER BY pr.created_at DESC LIMIT 1`,
        [project.id]
      );
      const p = rows[0];
      if (!p) return { bundle: null };
      const draft = (await designs.view(project.id, p.version)).draft!;
      const view = validateMetricView(draft.yaml).view;
      if (!view) throw new HttpError(409, `Version ${p.version} does not parse.`);
      const parent = await projects.get(actor, project.parentId);
      const files = bundleFiles({
        target: p.target,
        yaml: draft.yaml,
        view,
        tests: draft.tests,
        version: p.version,
        project: parent.name,
        subProject: project.name,
      });
      const name = `${p.target.split('.').pop()}_bundle.zip`;
      return {
        bundle: {
          target: p.target,
          version: p.version,
          fileName: name,
          files,
          zip: writeZip(files).toString('base64'),
        },
      };
    })
  );
}
