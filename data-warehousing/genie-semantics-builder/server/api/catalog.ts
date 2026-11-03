import type { Application, Request } from 'express';
import { z } from 'zod';
import { UC_NAME_PART } from '../../shared/brief';
import type { UcTable } from '../../shared/brief';
import { sqlString } from '../readiness/profile';
import { runStatement } from '../sql/runner';
import type { RunDeps } from '../sql/runner';
import { actorOf, handle } from './http';

const part = z.string().regex(UC_NAME_PART);
const catalogQuery = z.object({ catalog: part });
const schemaQuery = catalogQuery.extend({ schema: part });

/** Browsing runs as the user, so information_schema returns only what they can access. */
export function registerCatalogRoutes(app: Application, runFor: (req: Request) => RunDeps) {
  const read = async (req: Request, sql: string) =>
    (await runStatement(sql, { actor: actorOf(req), approved: false }, runFor(req))).rows;

  app.get(
    '/api/uc/catalogs',
    handle(async (req) =>
      (
        await read(
          req,
          `SELECT catalog_name FROM system.information_schema.catalogs
           WHERE NOT startswith(catalog_name, '__databricks') ORDER BY 1`
        )
      ).map((r) => r[0])
    )
  );

  app.get(
    '/api/uc/schemas',
    handle(async (req) => {
      const { catalog } = catalogQuery.parse(req.query);
      const rows = await read(
        req,
        `SELECT schema_name FROM system.information_schema.schemata
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
