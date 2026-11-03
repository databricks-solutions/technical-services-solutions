import path from 'node:path';
import { createApp, analytics, lakebase, server } from '@databricks/appkit';
import { loadMigrations, migrate } from './db/migrate';
import { registerProjectRoutes } from './api/projects';
import { servingDeps } from './llm/llm';

createApp({
  plugins: [analytics(), lakebase(), server()],
  // Runs as the app service principal, so it creates and owns the gsb schema.
  async onPluginsReady(appkit) {
    const applied = await migrate(appkit.lakebase.pool, await loadMigrations(path.resolve('server/db/migrations')));
    console.log(applied.length ? `Applied migrations: ${applied.join(', ')}` : 'Database schema is up to date');

    appkit.server.extend((app) => {
      registerProjectRoutes(app, appkit.lakebase.pool, (req) =>
        servingDeps((fn) => appkit.asUser(req).run(() => fn()))
      );
    });
  },
}).catch((err: unknown) => {
  console.error(err);
  process.exit(1);
});
