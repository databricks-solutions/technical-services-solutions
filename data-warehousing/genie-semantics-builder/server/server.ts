import path from 'node:path';
import type { Request } from 'express';
import { createApp, analytics, lakebase, server } from '@databricks/appkit';
import { loadMigrations, migrate } from './db/migrate';
import { registerCatalogRoutes } from './api/catalog';
import { registerProjectRoutes } from './api/projects';
import { registerDesignerRoutes } from './api/designer';
import { registerReadinessRoutes } from './api/readiness';
import { servingDeps } from './llm/llm';
import { warehouseDeps } from './sql/runner';

createApp({
  plugins: [analytics(), lakebase(), server()],
  // Runs as the app service principal, so it creates and owns the gsb schema.
  async onPluginsReady(appkit) {
    const applied = await migrate(appkit.lakebase.pool, await loadMigrations(path.resolve('server/db/migrations')));
    console.log(applied.length ? `Applied migrations: ${applied.join(', ')}` : 'Database schema is up to date');

    const pool = appkit.lakebase.pool;
    const asUser =
      (req: Request) =>
      <R>(fn: () => Promise<R>) =>
        appkit.asUser(req).run(() => fn());
    const llmFor = (req: Request) => servingDeps(asUser(req));
    appkit.server.extend((app) => {
      registerProjectRoutes(app, pool, llmFor);
      const runFor = (req: Request) => warehouseDeps(pool, asUser(req));
      registerCatalogRoutes(app, runFor);
      registerReadinessRoutes(app, pool, llmFor, runFor);
      registerDesignerRoutes(app, pool, llmFor, runFor);
    });
  },
}).catch((err: unknown) => {
  console.error(err);
  process.exit(1);
});
