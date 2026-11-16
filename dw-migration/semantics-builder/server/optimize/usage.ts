import type { FieldUsage } from '../../shared/usage';
import type { MetricView } from '../../shared/metricView';
import { literal } from '../designer/validate';

export const USAGE_DAYS = 90;

const since = (days: number) => `l.event_date >= current_date() - INTERVAL ${days} DAYS`;

/** Queries and users of each field of the view, from column lineage. Counts only. */
export function fieldUsageQuery(fullName: string, days = USAGE_DAYS): string {
  return [
    'SELECT lower(l.source_column_name) AS field, count(DISTINCT l.statement_id) AS queries,',
    '  count(DISTINCT l.created_by) AS users, max(l.event_time) AS last_used',
    'FROM system.access.column_lineage l',
    `WHERE l.source_table_full_name = ${literal(fullName.toLowerCase())} AND ${since(days)}`,
    'GROUP BY ALL',
    'ORDER BY queries DESC',
    'LIMIT 1000',
  ].join('\n');
}

/** Queries and users of the whole view, from table lineage. */
export function viewUsageQuery(fullName: string, days = USAGE_DAYS): string {
  return [
    'SELECT count(DISTINCT l.statement_id) AS queries, count(DISTINCT l.created_by) AS users',
    'FROM system.access.table_lineage l',
    `WHERE l.source_table_full_name = ${literal(fullName.toLowerCase())} AND ${since(days)}`,
  ].join('\n');
}

const REF = /\bMEASURE\s*\(\s*(`(?:[^`]|``)+`|[A-Za-z_]\w*)\s*\)/gi;
const unquote = (id: string) => (id.startsWith('`') ? id.slice(1, -1).replace(/``/g, '`') : id);

/** Every field of the view with its usage; a field that nobody read has 0 queries. Most used first. */
export function toFieldUsage(view: MetricView, rows: (string | null)[][]): FieldUsage[] {
  const byName = new Map(rows.map((r) => [r[0] ?? '', r]));
  const usedBy = new Map<string, string[]>();
  for (const m of view.measures)
    for (const ref of m.expr.matchAll(REF)) {
      const k = unquote(ref[1]).toLowerCase();
      if (k !== m.name.toLowerCase()) usedBy.set(k, [...(usedBy.get(k) ?? []), m.name]);
    }
  const fields = [
    ...view.dimensions.map((d) => ({ name: d.name, kind: 'dimension' as const })),
    ...view.measures.map((m) => ({ name: m.name, kind: 'measure' as const })),
  ];
  return fields
    .map((f) => {
      const r = byName.get(f.name.toLowerCase());
      return {
        ...f,
        queries: Number(r?.[1] ?? 0),
        users: Number(r?.[2] ?? 0),
        lastUsed: r?.[3] ?? null,
        usedBy: usedBy.get(f.name.toLowerCase()) ?? [],
      };
    })
    .sort((a, b) => b.queries - a.queries || a.name.localeCompare(b.name));
}
