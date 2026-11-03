import path from 'node:path';
import { createApp, analytics, lakebase, server, serving } from '@databricks/appkit';
import { loadMigrations, migrate } from './db/migrate';

createApp({
  plugins: [analytics(), lakebase(), server(), serving()],
  // Runs as the app service principal, so it creates and owns the gsb schema.
  async onPluginsReady(appkit) {
    const applied = await migrate(appkit.lakebase.pool, await loadMigrations(path.resolve('server/db/migrations')));
    console.log(applied.length ? `Applied migrations: ${applied.join(', ')}` : 'Database schema is up to date');
  },
}).catch((err: unknown) => {
  console.error(err);
  process.exit(1);
});
