import type { Application, Request } from 'express';
import { z } from 'zod';
import { UC_NAME_PART } from '../../shared/brief';
import type { UcTable } from '../../shared/brief';
import { quoteId, sqlString } from '../readiness/profile';
import { runStatement } from '../sql/runner';
import type { RunDeps } from '../sql/runner';
import { actorOf, handle } from './http';

const part = z.string().regex(UC_NAME_PART);
const purpose = z.object({ purpose: z.enum(['browse', 'publish']).default('browse') });
const catalogQuery = purpose.extend({ catalog: part });
const schemaQuery = catalogQuery.extend({ schema: part });

const MAX_PUBLISH_CATALOGS = 50;

// information_schema does not list owner privileges, so ownership is checked separately.
// This is a hint for the picker; the DDL itself is still checked by Unity Catalog.
export const CAN_CREATE = `(
  s.schema_owner = current_user() OR c.catalog_owner = current_user()
  OR is_account_group_member(s.schema_owner) OR is_account_group_member(c.catalog_owner)
  OR EXISTS (SELECT 1 FROM system.information_schema.schema_privileges p
             WHERE p.catalog_name = s.catalog_name AND p.schema_name = s.schema_name
               AND p.privilege_type IN ('CREATE_TABLE', 'ALL_PRIVILEGES')
               AND (p.grantee = current_user() OR is_account_group_member(p.grantee)))
  OR EXISTS (SELECT 1 FROM system.information_schema.catalog_privileges p
             WHERE p.catalog_name = s.catalog_name
               AND p.privilege_type IN ('CREATE_TABLE', 'ALL_PRIVILEGES')
               AND (p.grantee = current_user() OR is_account_group_member(p.grantee))))`;
const WRITABLE_SCHEMAS = `FROM system.information_schema.schemata s
  JOIN system.information_schema.catalogs c ON c.catalog_name = s.catalog_name
  WHERE s.schema_name <> 'information_schema' AND NOT startswith(s.catalog_name, '__databricks') AND ${CAN_CREATE}`;

/** Browsing runs as the user, so information_schema returns only what they can access. */
export function registerCatalogRoutes(app: Application, runFor: (req: Request) => RunDeps) {
  const read = async (req: Request, sql: string) =>
    (await runStatement(sql, { actor: actorOf(req), approved: false }, runFor(req))).rows;

  app.get(
    '/api/uc/catalogs',
    handle(async (req) => {
      if (purpose.parse(req.query).purpose === 'browse') {
        const rows = await read(
          req,
          `SELECT catalog_name FROM system.information_schema.catalogs
           WHERE NOT startswith(catalog_name, '__databricks') ORDER BY 1`
        );
        return rows.map((r) => r[0]);
      }
      const candidates = (
        await read(req, `SELECT DISTINCT s.catalog_name ${WRITABLE_SCHEMAS} ORDER BY 1 LIMIT ${MAX_PUBLISH_CATALOGS}`)
      ).map((r) => r[0] ?? '');
      // Foreign catalogs (Lakehouse Federation, Lakebase) and system catalogs cannot hold metric views.
      const regular = await Promise.all(
        candidates.map(async (name) => {
          const info = await read(req, `DESCRIBE CATALOG EXTENDED ${quoteId(name)}`);
          return info.some(([k, v]) => k === 'Catalog Type' && v === 'Regular') ? name : null;
        })
      );
      return regular.filter(Boolean);
    })
  );

  app.get(
    '/api/uc/schemas',
    handle(async (req) => {
      const { catalog, purpose } = catalogQuery.parse(req.query);
      const rows = await read(
        req,
        purpose === 'publish'
          ? `SELECT s.schema_name ${WRITABLE_SCHEMAS} AND s.catalog_name = ${sqlString(catalog)} ORDER BY 1`
          : `SELECT schema_name FROM system.information_schema.schemata
             WHERE catalog_name = ${sqlString(catalog)} AND schema_name <> 'information_schema' ORDER BY 1`
      );
      return rows.map((r) => r[0]);
    })
  );

  app.get(
    '/api/uc/tables',
    handle(async (req): Promise<UcTable[]> => {
      const { catalog, schema } = schemaQuery.parse(req.query);
      const rows = await read(
        req,
        `SELECT table_name, table_type FROM system.information_schema.tables
         WHERE table_catalog = ${sqlString(catalog)} AND table_schema = ${sqlString(schema)} ORDER BY 1`
      );
      return rows.map(([name, type]) => ({ name: name ?? '', type: type ?? '' }));
    })
  );
}
