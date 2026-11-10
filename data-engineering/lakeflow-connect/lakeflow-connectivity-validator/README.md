# Lakeflow CDC Source Validator

Pre-flight connectivity validator for **Lakeflow CDC database connectors**. Run this notebook before pipeline deployment or when troubleshooting connectivity to confirm that DNS, TCP, TLS, and (optionally) application-level access to your source database all work from your Databricks compute.

## Supported Sources

| Source       | Default Port | App Probe Driver                          |
| ------------ | ------------ | ----------------------------------------- |
| SQL Server   | 1433         | Built-in pure-Python TDS (no install)     |
| PostgreSQL   | 5432         | `psycopg2-binary` (auto-installed)        |
| MySQL        | 3306         | `mysql-connector-python` (auto-installed) |
| Oracle       | 1521 (TCPS usually 2484) | `oracledb` thin mode (auto-installed, no Instant Client) |

## What It Checks

The validator runs four checks in sequence. Each check only proceeds if the previous one passed:

1. **DNS Resolution** — Can the hostname be resolved to one or more IP addresses?
2. **TCP Connectivity** — Can a socket connection be opened to `host:port`? Distinguishes silent timeouts, active refusals, and network-unreachable errors with detailed troubleshooting hints.
3. **TLS** *(optional, enabled by default)* — SQL Server, PostgreSQL, and MySQL negotiate TLS *inside* their wire protocol (STARTTLS-style), not as implicit TLS on the port, so a raw port handshake would report false results. This step therefore emits an informational note and defers real TLS validation to the Application Probe (PostgreSQL `sslmode=require`, MySQL SSL, SQL Server TDS-wrapped TLS). **Oracle TCPS is implicit TLS on the port**, so for Oracle this step runs a real handshake with certificate verification (PASS / WARN on trust issues / FAIL).
4. **Application Probe** *(optional, disabled by default)* — Can the notebook authenticate to the database and run a trivial query (`SELECT 1`)? Requires credentials.

Additionally, the validator gathers **network context**:

- **Region match** — Detects whether the target database region matches the workspace region (cross-region adds latency and cost).
- **Egress / NAT IP** — Reports the public IP this compute presents, which you need to whitelist in security groups.
- **Network path type** — Identifies whether traffic routes over public internet or a private path.

## Quick Start

1. Open the notebook in Databricks.
2. Fill in the **widgets** at the top of the page:
   - `source_type` — `sqlserver`, `postgres`, `mysql`, or `oracle`
   - `host` — The database endpoint hostname
   - `port` — Leave blank to use the source default
   - `tls_enabled` — `auto` (default: on for SQL Server/PostgreSQL/MySQL, off for Oracle), `true`, or `false`. For Oracle, `true` means a TCPS listener
   - `run_app_probe` — `true` to test real DB login; `false` (default) for network-only
   - `username` / `database` — Only needed when `run_app_probe` is `true`. For Oracle, `database` is the **service name** (e.g. `ORCL` or a PDB service), not a SID
   - `secret_catalog` / `secret_schema` / `secret_key` — UC secret coordinates for the DB password (app probe only)
   - `secret_scope` — legacy workspace secret scope, used as a fallback when UC secret coordinates aren't provided (app probe only)
   - `timeout_seconds` — Connection timeout (default `5`)
3. Click **Run All**.

## Credentials

When `run_app_probe` is enabled, the app probe retrieves the database password from a **Unity Catalog secret** at runtime:

```python
db_pwd = dbutils.secrets.get(catalog="<catalog_name>", schema="<schema_name>", key="<secret_key>")
```

Fill in the `secret_catalog`, `secret_schema`, and `secret_key` widgets with the coordinates of your pre-created secret. The `username` and `database` are provided via regular widgets. Credentials are masked in the printed config output so the notebook is safe to demo or share.

If your workspace uses a **legacy secret scope** instead of UC secrets, leave the catalog/schema/key blank and set the `secret_scope` and `secret_key` widgets — the notebook falls back to:

```python
db_pwd = dbutils.secrets.get(scope="<scope_name>", key="<secret_key>")
```

> **Note:** Creating UC secrets is currently supported only via the **UI** or the **REST API** — not SQL or the CLI. See [Create a secret](https://docs.databricks.com/aws/en/security/secrets/unity-catalog-secrets#create-a-secret) for setup instructions. Legacy secret scopes can also be created via the Databricks CLI or Terraform.

## Notebook Structure

| Cell | Title                        | Purpose                                                                 |
| ---- | ---------------------------- | ----------------------------------------------------------------------- |
| 1    | Title                        | Markdown overview and secret setup instructions                         |
| 2    | Install optional probe drivers | `%pip install psycopg2-binary mysql-connector-python oracledb`        |
| 3    | User Configuration           | Widget definitions and `config` dictionary                              |
| 4    | Source Profiles              | Per-engine defaults (port, TLS, display name, driver notes)             |
| 5    | Core Utility Functions       | `resolve_host()`, `tcp_check()`, `tls_check()`, result aggregation      |
| 6    | Optional App Probes          | SQL Server (pure-Python TDS), PostgreSQL (`psycopg2`), MySQL, Oracle (`oracledb`) probes |
| 7    | Network Information          | Region extraction, egress IP detection, network path classification     |
| 8    | Main Runner                  | `run_validator()` — orchestrates all checks and prints a visual report  |

## Output

The validator prints a visual connection-path diagram showing where the connection is blocked (if anywhere), followed by detailed per-check results and network context. Example:

```
════════════════════════════════════════════════════════════════
  Lakeflow CDC Source Validator
  SQL Server  →  mydb.us-east-2.rds.amazonaws.com:1433
════════════════════════════════════════════════════════════════

  🗺️  Connection Path

  ✅ This Compute  ──▶  ✅ DNS Resolution  ──▶  ✅ Internet  ──▶  ✅ Security Group  ──▶  ✅ SQLSERVER

────────────────────────────────────────────────────────────────
  ✅  RESULT: PASS
────────────────────────────────────────────────────────────────
```

When a check fails, the output includes:

- The layer that failed (`BLOCKED AT: DNS / Security Group / TLS/SSL / <engine>`) and why. For app-probe failures the specific cause leads the detail and the recommendation, e.g. wrong username/password, unknown database or Oracle service name, server requires TLS, or `pg_hba.conf` rejection
- A targeted troubleshooting recommendation (cloud-provider-aware for AWS RDS and Azure SQL)
- The egress IP to whitelist in your firewall or security group
- A ready-to-use `aws ec2 authorize-security-group-ingress` CLI snippet (for AWS targets)

## Requirements

- **Compute**: Runs on Databricks Serverless or classic compute (Python).
- **Packages**: `psycopg2-binary`, `mysql-connector-python`, and `oracledb` are auto-installed by the notebook for the optional app probes. SQL Server uses a built-in pure-Python TDS implementation.
- **Oracle Native Network Encryption**: `oracledb` thin mode cannot negotiate NNE. If the server sets `SQLNET.ENCRYPTION_SERVER=REQUIRED`, the probe fails with `DPY-3001`; use a TCPS listener instead.
- **Permissions**: `READ SECRET` on the Unity Catalog secret is required for the app probe.

## Extending

To add a new source engine:

1. Add an entry to `SOURCE_PROFILES` in Cell 4 (default port, TLS setting, display name, driver note, and `implicit_tls: True` if TLS starts on connect rather than in-protocol).
2. Write an `app_probe_<engine>()` function in Cell 6.
3. Register it in the probe dispatcher in Cell 8 (`run_validator`).
