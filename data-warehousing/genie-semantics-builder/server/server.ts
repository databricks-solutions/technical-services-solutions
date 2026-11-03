import { createApp, analytics, getExecutionContext, getWarehouseId, lakebase, server, serving } from '@databricks/appkit';

createApp({
  plugins: [analytics(), lakebase(), server(), serving()],
  onPluginsReady(appkit) {
    // TEMPORARY OBO probe for phase (a) step 2. Remove after the live check.
    appkit.server.extend((app) => {
      app.get('/api/_obo-probe', async (req, res) => {
        const headers = Object.fromEntries(
          ['x-forwarded-access-token', 'x-forwarded-user', 'x-forwarded-email'].map((h) => [h, Boolean(req.header(h))])
        );
        try {
          const appIdentity = (await getExecutionContext().client.currentUser.me()).userName;
          const user = await appkit.asUser(req).run(async () => {
            const w = getExecutionContext().client;
            const me = (await w.currentUser.me()).userName;
            const stmt = await w.statementExecution.executeStatement({
              warehouse_id: await getWarehouseId(),
              statement: 'SELECT current_user() AS u',
              wait_timeout: '30s',
            });
            return { me, sqlCurrentUser: stmt.result?.data_array?.[0]?.[0] ?? null, sqlState: stmt.status?.state };
          });
          res.json({ headers, appIdentity, user });
        } catch (e) {
          res.status(500).json({ headers, error: e instanceof Error ? e.message : String(e) });
        }
      });
    });
  },
}).catch(console.error);
