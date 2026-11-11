import type { Consumer, ConsumerKind, FieldChanges } from '../../shared/promote';
import type { MetricView } from '../../shared/metricView';
import { literal } from './validate';

export const IMPACT_DAYS = 90;
const MAX_WATCHED = 20;

type Field = MetricView['dimensions'][number] | MetricView['measures'][number];
const norm = (s: string | undefined) => (s ?? '').replace(/\s+/g, ' ').trim().toLowerCase();
const meaning = (f: Field) => `${norm(f.expr)}|${JSON.stringify('window' in f ? (f.window ?? null) : null)}`;

/** What the new version changes in the fields of the view in Unity Catalog. Names compare without case. */
export function fieldChanges(before: MetricView, after: MetricView): FieldChanges {
  const all = (v: MetricView): Field[] => [...v.dimensions, ...v.measures];
  const next = new Map(all(after).map((f) => [f.name.toLowerCase(), f]));
  const prev = new Map(all(before).map((f) => [f.name.toLowerCase(), f]));
  const gone = all(before).filter((f) => !next.has(f.name.toLowerCase()));
  const added = all(after).filter((f) => !prev.has(f.name.toLowerCase()));
  const renamed: FieldChanges['renamed'] = [];
  const removed: string[] = [];
  for (const f of gone) {
    const to = added.find((a) => meaning(a) === meaning(f) && !renamed.some((r) => r.to === a.name));
    if (to) renamed.push({ from: f.name, to: to.name });
    else removed.push(f.name);
  }
  return {
    removed,
    renamed,
    changed: all(before)
      .filter((f) => {
        const n = next.get(f.name.toLowerCase());
        return n && meaning(n) !== meaning(f);
      })
      .map((f) => f.name),
    added: added.filter((a) => !renamed.some((r) => r.to === a.name)).map((a) => a.name),
    filterChanged: norm(before.filter) !== norm(after.filter),
  };
}

/** The fields whose users can break or see new numbers: removed, renamed and changed. */
export const watched = (c: FieldChanges | null) =>
  c ? [...c.removed, ...c.renamed.map((r) => r.from), ...c.changed].slice(0, MAX_WATCHED) : [];

const KINDS: [ConsumerKind, string][] = [
  ['genie_space', 'l.entity_metadata.genie_space_id'],
  ['dashboard', 'l.entity_metadata.dashboard_id'],
  ['alert', 'l.entity_metadata.alert_id'],
  ['app', 'l.entity_metadata.app_id'],
  ['job', 'l.entity_metadata.job_info.job_id'],
  ['pipeline', 'l.entity_metadata.dlt_pipeline_info.dlt_pipeline_id'],
  ['notebook', 'l.entity_metadata.notebook_id'],
  ['query', 'l.entity_metadata.sql_query_id'],
];

/**
 * Who read the view in the last days, from table lineage, and which watched fields each consumer read, from
 * column lineage. Returns counts and field names only, never user names or query text.
 */
export function impactQuery(fullName: string, fields: string[]): string {
  const kind = `CASE ${KINDS.map(([k, col]) => `WHEN ${col} IS NOT NULL THEN '${k}'`).join(' ')} ELSE 'adhoc' END`;
  const id = `coalesce(${KINDS.map(([, col]) => col).join(', ')})`;
  const where = (table: string) =>
    [
      `FROM system.access.${table} l`,
      `WHERE l.source_table_full_name = ${literal(fullName.toLowerCase())}`,
      `  AND l.event_date >= current_date() - INTERVAL ${IMPACT_DAYS} DAYS`,
    ].join('\n');
  const cols = fields.length
    ? [
        `c AS (SELECT ${kind} AS kind, ${id} AS id, collect_set(lower(l.source_column_name)) AS cols`,
        where('column_lineage'),
        `  AND lower(l.source_column_name) IN (${fields.map((f) => literal(f.toLowerCase())).join(', ')})`,
        'GROUP BY ALL)',
      ].join('\n')
    : 'c AS (SELECT CAST(NULL AS STRING) AS kind, CAST(NULL AS STRING) AS id, CAST(NULL AS ARRAY<STRING>) AS cols)';
  return [
    `WITH t AS (SELECT ${kind} AS kind, ${id} AS id, l.created_by, l.statement_id, l.event_time`,
    `${where('table_lineage')}),`,
    cols,
    'SELECT t.kind, t.id, count(DISTINCT t.created_by) AS users, count(DISTINCT t.statement_id) AS queries,',
    '  max(t.event_time) AS last_used, to_json(first(c.cols, true)) AS cols',
    'FROM t LEFT JOIN c ON c.kind = t.kind AND c.id <=> t.id',
    'GROUP BY ALL',
    'ORDER BY last_used DESC',
    'LIMIT 200',
  ].join('\n');
}

export function toConsumers(rows: (string | null)[][], fields: string[]): Consumer[] {
  return rows.map((r) => {
    const cols = new Set<string>(r[5] ? (JSON.parse(r[5]) as string[]) : []);
    return {
      kind: (KINDS.some(([k]) => k === r[0]) ? r[0] : 'adhoc') as ConsumerKind,
      id: r[1] ?? null,
      users: Number(r[2] ?? 0),
      queries: Number(r[3] ?? 0),
      lastUsed: r[4] ?? '',
      uses: fields.filter((f) => cols.has(f.toLowerCase())),
    };
  });
}
