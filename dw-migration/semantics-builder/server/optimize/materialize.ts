import { renderMetricView } from '../../shared/metricView';
import type { MetricView } from '../../shared/metricView';
import type {
  MaterializationSuggestion,
  Schedule,
  StressQueryResult,
  SuggestedMaterialization,
} from '../../shared/optimize';

/** Queries faster than this gain little from a materialization. */
export const MIN_MS = 1000;
export const MAX_VIEWS = 5;

type Measure = MetricView['measures'][number];

/** Rollup from a wider materialization works only for these. */
export const isAdditive = (m: Measure) =>
  !m.window && /^\s*(SUM|COUNT|MIN|MAX)\s*\(/i.test(m.expr) && !/^\s*COUNT\s*\(\s*DISTINCT\b/i.test(m.expr);

const slug = (dims: string[]) =>
  `mv_${dims
    .join('_')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_|_$/g, '')}`.slice(0, 60) || 'mv_total';

type Joins = MetricView['joins'];
const countJoins = (joins: Joins): number =>
  (joins ?? []).reduce((n, j) => n + 1 + countJoins((j as { joins?: Joins }).joins), 0);

const sameSet = (a: string[], b: string[]) => a.length === b.length && a.every((x) => b.includes(x));

/**
 * One aggregated materialization per dimension set of the slow queries, slowest first. A query whose
 * measures are all additive is served by rollup from a wider one instead of getting its own.
 */
export function suggestMaterializations(
  view: MetricView,
  runId: string,
  queries: StressQueryResult[]
): MaterializationSuggestion {
  const measures = new Map(view.measures.map((m) => [m.name, m]));
  const views: SuggestedMaterialization[] = [];
  const skipped: MaterializationSuggestion['skipped'] = [];
  const ordered = [...queries].sort((a, b) => (b.warmMs ?? -1) - (a.warmMs ?? -1));

  for (const q of ordered) {
    if (q.warmMs === null) {
      skipped.push({ label: q.label, reason: 'It has no measured run.' });
      continue;
    }
    if (q.warmMs < MIN_MS) {
      skipped.push({ label: q.label, reason: `It already runs in under ${MIN_MS / 1000} s.` });
      continue;
    }
    const same = views.find((v) => sameSet(v.dimensions, q.dimensions));
    const additive = q.measures.every((m) => measures.get(m) && isAdditive(measures.get(m)!));
    const wider = additive ? views.find((v) => q.dimensions.every((d) => v.dimensions.includes(d))) : undefined;
    const target = same ?? wider;
    if (target) {
      for (const m of q.measures) if (!target.measures.includes(m)) target.measures.push(m);
      target.queries.push(q.label);
      continue;
    }
    if (views.length >= MAX_VIEWS) {
      skipped.push({ label: q.label, reason: `The suggestion stops at ${MAX_VIEWS} materializations.` });
      continue;
    }
    let name = slug(q.dimensions);
    while (views.some((v) => v.name === name)) name = `${name}_2`;
    views.push({
      name,
      type: 'aggregated',
      dimensions: [...q.dimensions],
      measures: [...q.measures],
      queries: [q.label],
      reason: `${q.label} takes ${(q.warmMs / 1000).toFixed(1)} s.`,
    });
  }

  for (const v of views) {
    const exact = v.measures.filter((m) => measures.get(m) && !isAdditive(measures.get(m)!));
    if (exact.length) v.reason += ` ${exact.join(', ')} need an exact match: group by exactly these dimensions.`;
  }

  const notes = [
    'Needs serverless compute and Databricks Runtime 17.3 or above. Row filters, column masks and parameters block it.',
    'Refreshes bill as Lakeflow pipeline DBUs. Matched queries return data from the last refresh.',
    'After a materialization exists, the owner of the metric view cannot change, and a group cannot own it.',
  ];
  if (skipped.some((s) => s.reason.startsWith('The suggestion stops')) && countJoins(view.joins) >= 3)
    notes.push('Many query shapes and joins: one unaggregated materialization of the joined data can serve them all.');
  return { basedOnRun: runId, views, skipped, notes };
}

export function withMaterialization(view: MetricView, schedule: Schedule, views: SuggestedMaterialization[]) {
  return renderMetricView({
    ...view,
    materialization: {
      schedule,
      mode: 'relaxed',
      materialized_views: views.map((v) => ({
        name: v.name,
        type: v.type,
        dimensions: v.dimensions,
        measures: v.measures,
      })),
    },
  });
}

/**
 * The materialization a query plan reads, from EXPLAIN EXTENDED, or null when it reads the sources. The plan
 * shows the name with a suffix (mv_by_month_...), so the longest name found wins over its prefixes.
 */
export function matchedName(plan: string, names: string[]): string | null {
  if (!plan.includes('__materialization_mat_')) return null;
  const found = names.filter((n) => plan.includes(n)).sort((a, b) => b.length - a.length);
  return found[0] ?? 'unknown';
}
