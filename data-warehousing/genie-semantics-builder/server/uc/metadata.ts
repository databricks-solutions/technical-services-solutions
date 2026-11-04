import { getExecutionContext, getWarehouseId, isInUserContext } from '@databricks/appkit';
import type { TableProfile } from '../readiness/profile';
import type { RunAsUser } from '../sql/runner';

/** The parts of a Unity Catalog table the app reads. Shaped like the REST API's TableInfo. */
export interface UcTableInfo {
  name?: string;
  full_name?: string;
  table_type?: string;
  comment?: string;
  owner?: string;
  columns?: { name?: string; type_text?: string; comment?: string }[];
  table_constraints?: {
    primary_key_constraint?: { child_columns: string[] };
    foreign_key_constraint?: { child_columns: string[]; parent_table: string; parent_columns: string[] };
  }[];
}

export interface EffectiveGrant {
  principal: string;
  privileges: string[];
}

/**
 * Metadata reads through the Unity Catalog REST API, as the calling user. The SQL warehouse is
 * kept for real queries and approved DDL.
 */
export interface UcDeps {
  catalogs(): Promise<string[]>;
  schemas(catalog: string): Promise<string[]>;
  tables(catalog: string, schema: string, withColumns: boolean): Promise<UcTableInfo[]>;
  table(fullName: string): Promise<UcTableInfo>;
  /** Effective privileges on a securable, inherited ones included, for every principal. */
  effective(type: 'catalog' | 'schema' | 'table', fullName: string): Promise<EffectiveGrant[]>;
  /** The user name and the display names of the user's groups. */
  me(): Promise<{ userName: string; groups: string[] }>;
  /** Resolves when the user can see the app's SQL warehouse. */
  warehouse(): Promise<void>;
}

const MAX_ITEMS = 5000;

async function collect<T>(items: AsyncIterable<T>): Promise<T[]> {
  const out: T[] = [];
  for await (const item of items) {
    out.push(item);
    if (out.length >= MAX_ITEMS) break;
  }
  return out;
}

function client() {
  if (!isInUserContext()) throw new Error('Unity Catalog reads must run as the calling user (OBO), never as the app');
  // AppKit's facade types only a few services; the legacy client carries the Unity Catalog ones.
  return getExecutionContext().client.toLegacyWorkspaceClient();
}

export function ucDeps(runAsUser: RunAsUser): UcDeps {
  return {
    catalogs: () =>
      runAsUser(async () =>
        (await collect(client().catalogs.list({})))
          .map((c) => c.name ?? '')
          .filter((n) => n && !n.startsWith('__databricks'))
          .sort()
      ),
    schemas: (catalog) =>
      runAsUser(async () =>
        (await collect(client().schemas.list({ catalog_name: catalog })))
          .map((s) => s.name ?? '')
          .filter((n) => n && n !== 'information_schema')
          .sort()
      ),
    tables: (catalog, schema, withColumns) =>
      runAsUser(async () =>
        (
          await collect(
            client().tables.list({
              catalog_name: catalog,
              schema_name: schema,
              omit_columns: !withColumns,
              omit_properties: true,
              omit_username: true,
            })
          )
        ).sort((a, b) => (a.name ?? '').localeCompare(b.name ?? ''))
      ),
    table: (fullName) => runAsUser(() => client().tables.get({ full_name: fullName })),
    effective: (type, fullName) =>
      runAsUser(async () => {
        const res = await client().grants.getEffective({ securable_type: type, full_name: fullName });
        return (res.privilege_assignments ?? []).map((a) => ({
          principal: a.principal ?? '',
          privileges: (a.privileges ?? []).map((p) => String(p.privilege ?? '')),
        }));
      }),
    me: () =>
      runAsUser(async () => {
        const me = await client().currentUser.me();
        return { userName: me.userName ?? '', groups: (me.groups ?? []).map((g) => g.display ?? '').filter(Boolean) };
      }),
    warehouse: () =>
      runAsUser(async () => {
        await client().warehouses.get({ id: await getWarehouseId() });
      }),
  };
}

/** Table metadata in the shape the readiness checks use. Names, types, comments and keys only. */
export function profileFromTable(fullName: string, t: UcTableInfo): TableProfile {
  const constraints = t.table_constraints ?? [];
  return {
    fullName,
    comment: t.comment ?? '',
    columns: (t.columns ?? []).map((c) => ({ name: c.name ?? '', type: c.type_text ?? '', comment: c.comment ?? '' })),
    primaryKey: constraints.find((c) => c.primary_key_constraint)?.primary_key_constraint?.child_columns ?? [],
    foreignKeys: constraints.flatMap((c) =>
      c.foreign_key_constraint
        ? [
            {
              columns: c.foreign_key_constraint.child_columns,
              references: c.foreign_key_constraint.parent_table,
              refColumns: c.foreign_key_constraint.parent_columns,
            },
          ]
        : []
    ),
  };
}
