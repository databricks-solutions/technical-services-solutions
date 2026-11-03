import { createApp, analytics, lakebase, server, serving } from '@databricks/appkit';

createApp({
  plugins: [analytics(), lakebase(), server(), serving()],
}).catch(console.error);
