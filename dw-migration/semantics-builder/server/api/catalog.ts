import type { Application, Request } from 'express';
import { z } from 'zod';
import { UC_NAME_PART } from '../../shared/brief';
import type { UcTable } from '../../shared/brief';
import type { UcDeps } from '../uc/metadata';
import { actorOf, handle } from './http';

const part = z.string().regex(UC_NAME_PART);
const catalogQuery = z.object({ catalog: part });
const schemaQuery = catalogQuery.extend({ schema: part });

/** Browsing uses the Unity Catalog API as the user, so it lists only what they can access. */
export function registerCatalogRoutes(app: Application, ucFor: (req: Request) => UcDeps) {
  app.get(
    '/api/uc/catalogs',
    handle((req) => {
      actorOf(req);
      return ucFor(req).catalogs();
    })
  );

  app.get(
    '/api/uc/schemas',
    handle((req) => {
      actorOf(req);
      return ucFor(req).schemas(catalogQuery.parse(req.query).catalog);
    })
  );

  app.get(
    '/api/uc/tables',
    handle(async (req): Promise<UcTable[]> => {
      actorOf(req);
      const { catalog, schema } = schemaQuery.parse(req.query);
      const tables = await ucFor(req).tables(catalog, schema, false);
      return tables.map((t) => ({ name: t.name ?? '', type: t.table_type ?? '' }));
    })
  );
}
