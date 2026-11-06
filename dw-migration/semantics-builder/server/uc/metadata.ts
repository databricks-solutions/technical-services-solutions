import { getExecutionContext, getWarehouseId, isInUserContext } from '@databricks/appkit';
import type { StressAttempt } from '../../shared/optimize';
import type { TableProfile } from '../readiness/profile';
import type { RunAsUser } from '../sql/runner';

/** The parts of a Unity Catalog table the app reads. Shaped like the REST API's TableInfo. */
export interface UcTableInfo {
  name?: string;
  full_name?: string;
  table_type?: string;
  comment?: string;
  owner?: string;
  /** The YAML of a metric view, or the SQL of a view. */
  view_definition?: string;
  columns?: { name?: string; type_text?: string; comment?: string }[];
  table_constraints?: {
    primary_key_constraint?: { child_columns: string[] };
    foreign_key_constraint?: { child_columns: string[]; parent_table: string; parent_columns: string[] };
  }[];
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
  /** Owner of a catalog or schema. */
  owner(type: 'catalog' | 'schema', fullName: string): Promise<string | undefined>;
  /** The user name and the display names of the user's groups. */
  me(): Promise<{ userName: string; groups: string[] }>;
  /** Resolves when the user can see the app's SQL warehouse. */
  warehouse(): Promise<void>;
  /** Query History metrics of the user's own statements. Missing ids are not ready yet. */
  queryMetrics(statementIds: string[]): Promise<Map<string, Omit<StressAttempt, 'wallMs'>>>;
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
    owner: (type, fullName) =>
      runAsUser(async () =>
        type === 'catalog'
          ? (await client().catalogs.get({ name: fullName })).owner
          : (await client().schemas.get({ full_name: fullName })).owner
      ),
    me: () =>
      runAsUser(async () => {
        const me = await client().currentUser.me();
        return { userName: me.userName ?? '', groups: (me.groups ?? []).map((g) => g.display ?? '').filter(Boolean) };
      }),
    warehouse: () =>
      runAsUser(async () => {
        await client().warehouses.get({ id: await getWarehouseId() });
      }),
    queryMetrics: (ids) =>
      runAsUser(async () => {
        const out = new Map<string, Omit<StressAttempt, 'wallMs'>>();
        for (let i = 0; i < ids.length; i += 50) {
          const page = await client().queryHistory.list({
            filter_by: { statement_ids: ids.slice(i, i + 50) },
            include_metrics: true,
            max_results: 100,
          });
          for (const h of page.res ?? []) {
            const m = h.metrics;
            // Metrics arrive a few seconds after the statement ends.
            if (!h.query_id || m?.execution_time_ms === undefined) continue;
            out.set(h.query_id, {
              statementId: h.query_id,
              execMs: m.execution_time_ms,
              taskMs: m.task_total_time_ms,
              readBytes: m.read_bytes,
              prunedBytes: m.pruned_bytes,
              rowsRead: m.rows_read_count,
              spillBytes: m.spill_to_disk_bytes,
              fromCache: m.result_from_cache,
            });
          }
        }
        return out;
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
