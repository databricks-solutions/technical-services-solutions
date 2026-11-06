import path from 'node:path';
import type { Request } from 'express';
import { createApp, analytics, lakebase, server } from '@databricks/appkit';
import { loadMigrations, migrate } from './db/migrate';
import { registerCatalogRoutes } from './api/catalog';
import { registerOptimizeRoutes } from './api/optimize';
import { registerDictionaryRoutes } from './api/dictionary';
import { registerProjectRoutes } from './api/projects';
import { registerDesignerRoutes } from './api/designer';
import { registerPatternRoutes } from './api/patterns';
import { loadPatterns } from './patterns/library';
import { registerReadinessRoutes } from './api/readiness';
import { ucDeps } from './uc/metadata';
import { registerGenieRoutes } from './api/genie';
import { registerPromoteRoutes } from './api/promote';
import { registerLibraryRoutes } from './api/library';
import { registerImportRoutes } from './api/import';
import { registerGovernRoutes } from './api/govern';
import { genieDeps } from './genie/client';
import { servingDeps } from './llm/llm';
import { warehouseDeps } from './sql/runner';

createApp({
  plugins: [analytics(), lakebase(), server()],
  // Runs as the app service principal, so it creates and owns the gsb schema.
  async onPluginsReady(appkit) {
    const applied = await migrate(appkit.lakebase.pool, await loadMigrations(path.resolve('server/db/migrations')));
    console.log(applied.length ? `Applied migrations: ${applied.join(', ')}` : 'Database schema is up to date');

    const { patterns, skipped } = await loadPatterns(path.resolve('patterns'));
    console.log(`Loaded ${patterns.length} patterns`);
    for (const s of skipped) console.warn(`Skipped pattern ${s}`);

    const pool = appkit.lakebase.pool;
    const asUser =
      (req: Request) =>
      <R>(fn: () => Promise<R>) =>
        appkit.asUser(req).run(() => fn());
    const llmFor = (req: Request) => servingDeps(asUser(req));
    appkit.server.extend((app) => {
      const runFor = (req: Request) => warehouseDeps(pool, asUser(req));
      const ucFor = (req: Request) => ucDeps(asUser(req));
      registerProjectRoutes(app, pool, llmFor, runFor, (req) => genieDeps(asUser(req)));
      registerCatalogRoutes(app, ucFor);
      registerReadinessRoutes(app, pool, llmFor, runFor, ucFor);
      registerDesignerRoutes(app, pool, llmFor, runFor, ucFor, patterns);
      registerPatternRoutes(app, pool, patterns, runFor);
      registerOptimizeRoutes(app, pool, runFor, ucFor);
      registerDictionaryRoutes(app, pool, runFor);
      registerPromoteRoutes(app, pool, runFor, ucFor);
      registerLibraryRoutes(app, pool);
      registerImportRoutes(app, pool, ucFor);
      registerGovernRoutes(app, pool, runFor, ucFor);
      registerGenieRoutes(app, pool, runFor, (req) => genieDeps(asUser(req)));
      // The workspace URL for Catalog Explorer links. Apps set DATABRICKS_HOST; nothing is hardcoded.
      const host = process.env.DATABRICKS_HOST?.trim().replace(/\/+$/, '') ?? '';
      const workspaceUrl = host ? (host.startsWith('http') ? host : `https://${host}`) : null;
      app.get('/api/config', (_req, res) => res.json({ workspaceUrl }));
    });
  },
}).catch((err: unknown) => {
  console.error(err);
  process.exit(1);
});
