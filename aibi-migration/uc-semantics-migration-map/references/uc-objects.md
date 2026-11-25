# Unity Catalog objects: what each is, the exact API `apply.py` uses, privileges, limits

**Verified end to end** on a real account (create → re-apply no-op → update → publish → prune) from a serverless
Databricks notebook, 2026-11-23. Sources: Databricks docs (*Unity Catalog semantics*, Domain / Knowledge Page / UC Wiki
API references).

| Object | What it is | API used by `apply.py` | Privileges |
|---|---|---|---|
| **Governed tag** | A domain *is* a governed tag with UI treatment | `GET/POST /api/2.1/tag-policies` (body `{tag_key, description}`), `DELETE …/{tag_key}` | create governed tags (account admin) |
| **Domain / subdomain** | Account-level grouping by governed tag, ≤5 levels. Subdomain tag = `parent/child` | `GET/POST /api/2.0/domains` (`?domain_id=` client-supplied; body `tag_key, draft, subtitle, description, parent_domain_id`), `PATCH /api/2.0/domains/{id}?update_mask=`, `DELETE` | `MANAGE DISCOVER` (account & workspace admins by default) |
| **Metric view** | UC securable defined in YAML | `CREATE OR REPLACE VIEW <fqn> WITH METRICS LANGUAGE YAML AS $$ … $$` on a SQL warehouse (DBR ≥ 17.3); existence via `GET /api/2.1/unity-catalog/tables/{fqn}` | `USE CATALOG`, `USE SCHEMA`, `CREATE TABLE` on the schema; `SELECT` on sources |
| **Domain membership** | Tag the asset with the domain's governed tag | `ALTER TABLE\|VIEW <fqn> SET TAGS ('<tag>')`; read via `<cat>.information_schema.table_tags` | `APPLY TAG` + `ASSIGN` on the tag |
| **Page** | Authoritative definition of a concept, per domain; Genie One cites it | `GET/POST /api/2.0/knowledge/pages` (`domain: "domains/{id}"`, `display_name`, `body`, `synonyms`, `description`, `state: DRAFT\|PUBLISHED`; `?request_id=` UUIDv4), `PATCH …/{name}?update_mask=`, `DELETE` | `MANAGE PAGES` (all account users by default); publishing needs Page Manager / domain admin |
| **Wiki** (Beta) | Documentation of one table in Catalog Explorer | `GET/PATCH /api/2.0/knowledge/tables/{fqn}/page` (`update_mask=body,description,state`; PATCH creates) | write on the table |

## Behaviours learned the hard way (all handled in code)

- **List endpoints return short pages *and* a `next_page_token`.** Always paginate to the end (`paged()`); one page can miss an existing object.
- **Pages' `request_id` must be a UUIDv4.** We derive a deterministic v4 from the object key, so a retry returns the existing page instead of a duplicate.
- **`CREATE OR REPLACE VIEW` drops the view's tags.** After any view (re)creation its domain tags are re-applied.
- **A DRAFT wiki doesn't read back like a published one** → sync is decided by the recorded applied-hash first, live content second.
- **Domains, governed tags and Pages are account-wide, and real accounts are crowded** (the test accounts held 177–1,001 domains and up to 3,075 governed tags). Use `target.tag_prefix`; an existing domain on a tag this tool didn't create is *blocked* unless `--adopt`; the plan flags when a governed tag is being reused.
- **Subdomains** use `parent_domain_id`; a parent is immutable (plan blocks a hierarchy change).
- **Idempotent domain ids**: `ucsm-<key>`; Page/wiki identity is (domain, display name) / table.

## Not available through the API (manual)

- Domain **display names** (UI only) and Discover-page / domain-page **sections**.
- **Publishing** drafts needs the right permission (`--publish` uses `state: PUBLISHED` / `draft: false`).
- Pages: no CMK; not in GovCloud; limited under some compliance security profiles.

## Idempotency mechanics

| Object | Identity | "Changed?" test |
|---|---|---|
| Domain | live match on `tag_key`; id `ucsm-<key>` | compare subtitle/description to live; parent mismatch ⇒ block |
| Metric view | fully-qualified name | recorded YAML hash == current ⇒ noop; else live definition compare; else `CREATE OR REPLACE` (after validate-on-a-throw-away-view) |
| Tag | (securable, tag) | present in `information_schema.table_tags` ⇒ noop (forced re-apply after a view replace) |
| Page | (domain, display_name) | live GET compare of body/description/synonyms (+ state when `--publish`) |
| Wiki | table | recorded hash, else live body |

Known limit: a UI edit to an existing Metric View whose recorded hash still matches isn't detected until the YAML changes.

## Terraform alternative

`databricks_domain` exists in the Databricks Terraform provider; estates that manage domains as code can generate `.tf` from `semantic-map.yaml` instead of using `apply.py` for domains.
