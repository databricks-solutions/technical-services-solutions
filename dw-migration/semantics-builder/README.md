# STS Semantics Builder

A Databricks App that helps teams design, validate, optimize and govern Unity Catalog metric views,
with an LLM advisor behind every step and a human approval in front of every change.

## Modules

| Module                                                                    | Status    |
| ------------------------------------------------------------------------- | --------- |
| Intent & Context: Semantic Brief draft, refine, confirm                   | Available |
| Source Readiness: checks, AI scoring, approval-gated metadata fixes       | Available |
| Metric Designer: AI design, YAML editor, join diagram, sandbox validation | Available |
| Optimize: best practices, stress test, materialization, cost, Ask Genie   | Available |
| Metric views library, import from UC, promote, restore, owner and grants  | Available |
| Migration & Drift                                                         | Planned   |

## Security model

- **User identity for data.** Warehouse queries and model calls run on behalf of the signed-in user (OBO).
  Catalog, schema and table pickers list only what that user can access. Production fails closed
  without the user headers from the Databricks Apps proxy.
- **App identity for metadata only.** The app service principal owns the Lakebase `gsb` schema
  (projects, briefs, reports, fixes, audit log) and writes MLflow traces. It never reads customer data.
- **One path to the warehouse.** Every statement passes an allowlist (reads, `DESCRIBE`, and a fixed set
  of metadata DDL: comments, keys, tags, metric views, read grants and revokes, and the owner of a view). One statement at a time, no comments.
- **The model never writes SQL.** It proposes names and text. The server checks names against the real
  table, quotes every identifier and literal, and builds the statement.
- **Exact SQL, human approval.** A fix runs only with the statements the user reviewed. It runs once,
  as the user, and is written to an append-only audit log before and after execution.
- **No content in telemetry.** Logs and MLflow traces hold prompt id and version, latency, tokens and
  outcome. Prompts, responses and catalog details stay inside the app.
- **Validation stays in a sandbox.** Draft metric views are created only in the schema set by the
  `sandbox_schema` bundle variable, never in a name from the request. Tests are reads. Only pass or fail,
  row counts and the SQL are stored, never result values.
- **Untrusted input stays data.** User text and catalog metadata go to the model inside delimited
  `untrusted_data` blocks. Model output is validated against a schema and repaired once at most.

## Demo: TPC-H (phase a)

1. **Projects > New project.** Pick the target catalog and schema from the dropdowns.
2. **Intent & Context.** Describe the goal, for example: net revenue (extended price minus discount,
   without tax), order count and average order value by month, quarter and year, by customer market
   segment, nation and region. Pick `samples.tpch` tables: `lineitem`, `orders`, `customer`, `nation`, `region`.
3. **Generate brief**, ask for a change if needed, then **Confirm brief**. Confirming registers the tables.
4. **Source Readiness > Assess sources.** Each table gets deterministic checks, a role, a readiness
   score and AI findings. Proposed fixes show the exact SQL.
5. **Review and apply** a fix. `samples` is read-only, so the fix fails with `PERMISSION_DENIED` and
   nothing changes. To see fixes succeed, copy the tables into a schema you own and assess that copy:

   ```sql
   CREATE TABLE <catalog>.<schema>.orders AS SELECT * FROM samples.tpch.orders;
   ```

   Apply primary keys before the foreign keys that reference them.

## Demo: TPC-H (phase b)

Start from a project with a confirmed brief and assessed sources (phase a).

1. **Metric Designer > Generate design.** The AI reads the brief and the live table metadata. It returns
   a structure, and the app writes the YAML. Expect `lineitem` as the fact table and the snowflake
   `orders > customer > nation > region`. Measures: Net Revenue, Order Count, and Average Order Value as a ratio
   of the two.
2. **Review.** The join tree flags joins whose target has no declared primary key, because those joins can
   count rows twice. Each measure shows its type (additive, not additive, ratio) and a plain explanation.
3. **Edit.** Change a column name in the YAML and select **Save version**. The server checks every
   column against the tables and reports the line. Ask the AI for a change, for example "add Gross Revenue
   without discount". Every change adds a version.
4. **Validate in sandbox.** Review the exact `CREATE OR REPLACE VIEW ... WITH METRICS` statement and run it.
   Each test case runs as a `MEASURE()` query and as plain SQL that the app derives from the YAML. Open a test
   to see both queries. The version becomes **Validated** when every test matches.

## Prerequisites

- Node.js v22+ and pnpm
- Databricks CLI (for deployment)
- Access to a Databricks workspace

## Databricks Authentication

### Local Development

For local development, configure your environment variables by creating a `.env` file:

```bash
cp .env.example .env
```

Edit `.env` and set the environment variables you need:

```env
DATABRICKS_HOST=https://your-workspace.cloud.databricks.com
DATABRICKS_APP_PORT=8000
# ... other environment variables, depending on the plugins you use
```

#### Lakebase Configuration

The Lakebase plugin requires additional environment variables for PostgreSQL connectivity. To learn how to configure the Lakebase plugin, see the [Lakebase plugin documentation](https://developers.databricks.com/docs/appkit/v0/plugins/lakebase).

### CLI Authentication

The Databricks CLI requires authentication to deploy and manage apps. Configure authentication using one of these methods:

#### OAuth U2M

Interactive browser-based authentication with short-lived tokens:

```bash
databricks auth login --host https://your-workspace.cloud.databricks.com
```

This will open your browser to complete authentication. The CLI saves credentials to `~/.databrickscfg`.

#### Configuration Profiles

Use multiple profiles for different workspaces:

```ini
[DEFAULT]
host = https://dev-workspace.cloud.databricks.com

[production]
host = https://prod-workspace.cloud.databricks.com
client_id = prod-client-id
client_secret = prod-client-secret
```

Deploy using a specific profile:

```bash
databricks bundle deploy --profile production
```

**Note:** Personal Access Tokens (PATs) are legacy authentication. OAuth is strongly recommended for better security.

## Getting Started

### Install Dependencies

```bash
pnpm install
```

### Development

Run the app in development mode with hot reload:

```bash
pnpm run dev
```

The app will be available at the URL shown in the console output.

### Build

Build both client and server for production:

```bash
pnpm run build
```

This creates:

- `dist/server.js` - Compiled server bundle
- `client/dist/` - Bundled client assets

### Production

Run the production build:

```bash
pnpm start
```

## Code Quality

There are a few commands to help you with code quality:

```bash
# Type checking
pnpm run typecheck

# Linting
pnpm run lint
pnpm run lint:fix

# Formatting
pnpm run format
pnpm run format:fix
```

## Deployment with Databricks Asset Bundles

The app command and environment are set in `databricks.yml` (`resources.apps.app.config`), not in
`app.yaml`. Set `sandbox_schema` per target to a `catalog.schema` where app users can create views.

### 1. Configure Bundle

Update `databricks.yml` with your workspace settings:

```yaml
targets:
  default:
    workspace:
      host: https://your-workspace.cloud.databricks.com
```

Make sure to replace all placeholder values in `databricks.yml` with your actual resource IDs.

### 2. Deploy

Deploy and start the app with a single command:

```bash
databricks apps deploy
```

`databricks apps deploy` validates the project, deploys it, starts the app, and prints its URL.

### Deploy to Production

1. Configure the production target in `databricks.yml`
2. Deploy to production:

```bash
databricks apps deploy -t prod
```

> **Restarting a stopped app:** apps stop after a period of inactivity. To start one again without redeploying, run `databricks apps start <APP_NAME>`.

## Project Structure

```
* client/          # React frontend
  * src/           # Source code
  * public/        # Static assets
* server/          # Express backend
  * server.ts      # Server entry point
  * routes/        # Routes
* shared/          # Shared types
* config/          # Configuration
  * queries/       # SQL query files
* databricks.yml   # Bundle and app configuration (command, env, resources)
* .env.example     # Environment variables example
```

## Tech Stack

- **Backend**: Node.js, Express
- **Frontend**: React.js, TypeScript, Vite, Tailwind CSS, React Router
- **UI Components**: Radix UI, shadcn/ui
- **Databricks**: AppKit SDK
