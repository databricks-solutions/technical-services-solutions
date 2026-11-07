import type { TestCase } from '../../shared/designer';
import type { MetricView } from '../../shared/metricView';
import type { StressAttempt, StressFlag, WorkloadQuery } from '../../shared/optimize';
import { quoteId, quoteName } from '../readiness/profile';

export const MAX_QUERIES = 25;
export const MAX_REPEATS = 5;
export const MAX_RESULT_ROWS = 1000;
/** A query that reads this much without pruning a byte is a full scan worth a look. */
const FULL_SCAN_BYTES = 2 ** 30;

const REF = /\bMEASURE\s*\(\s*(`(?:[^`]|``)+`|[A-Za-z_]\w*)\s*\)/gi;
const unquote = (id: string) => (id.startsWith('`') ? id.slice(1, -1).replace(/``/g, '`') : id);

/** The dimensions a measure needs in the GROUP BY: the order of its window, and of the measures it uses. */
function windowOrders(view: MetricView): Map<string, Set<string>> {
  const byName = new Map(view.measures.map((m) => [m.name.toLowerCase(), m]));
  const memo = new Map<string, Set<string>>();
  const visit = (name: string, seen: Set<string>): Set<string> => {
    const key = name.toLowerCase();
    if (memo.has(key)) return memo.get(key)!;
    const m = byName.get(key);
    const out = new Set<string>((m?.window ?? []).map((w) => w.order));
    if (m && !seen.has(key)) {
      seen.add(key);
      for (const [, ref] of m.expr.matchAll(REF)) for (const o of visit(unquote(ref), seen)) out.add(o);
    }
    memo.set(key, out);
    return out;
  };
  return new Map(view.measures.map((m) => [m.name, visit(m.name, new Set())]));
}

const key = (q: Pick<WorkloadQuery, 'dimensions' | 'measures'>) =>
  `${[...q.dimensions].sort().join('|')}#${[...q.measures].sort().join('|')}`;

const labelFor = (dimensions: string[], measures: string[]) => {
  const what = measures.length > 2 ? `${measures[0]} and ${measures.length - 1} more` : measures.join(' and ');
  return dimensions.length ? `${what} by ${dimensions.join(', ')}` : what;
};

/** The validation tests, then each dimension with every measure it can show. */
export function buildWorkload(view: MetricView, tests: TestCase[]): WorkloadQuery[] {
  const orders = windowOrders(view);
  const out: WorkloadQuery[] = tests.map((t) => ({
    label: t.name,
    dimensions: t.dimensions,
    measures: t.measures,
    origin: 'test' as const,
  }));
  const seen = new Set(out.map(key));
  for (const d of view.dimensions) {
    const measures = view.measures
      .filter((m) => [...orders.get(m.name)!].every((o) => o.toLowerCase() === d.name.toLowerCase()))
      .map((m) => m.name);
    const q = { label: labelFor([d.name], measures), dimensions: [d.name], measures, origin: 'generated' as const };
    if (measures.length && !seen.has(key(q))) {
      seen.add(key(q));
      out.push(q);
    }
  }
  return out.slice(0, MAX_QUERIES);
}

/**
 * A unique literal column makes each run miss the result cache, so the numbers show real work. A no-op
 * filter is not enough: the metric view rewrite drops it and the query hits the cache.
 */
export function stressSql(fullName: string, q: Pick<WorkloadQuery, 'dimensions' | 'measures'>, tag: number): string {
  const cols = [...q.dimensions.map(quoteId), ...q.measures.map((m) => `MEASURE(${quoteId(m)}) AS ${quoteId(m)}`)];
  const group = q.dimensions.length ? ' GROUP BY ALL' : '';
  return `SELECT ${cols.join(', ')}, 'gsb-${Math.trunc(tag)}' AS gsb_run FROM ${quoteName(fullName)}${group} LIMIT ${MAX_RESULT_ROWS + 1}`;
}

const median = (xs: number[]) => {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
};

/** Execution time when the Query History has it, otherwise the time the app waited. */
const timeOf = (a: StressAttempt) => a.execMs ?? a.wallMs;

export function summarize(attempts: StressAttempt[], targetMs: number) {
  // A cached result did no work, so it says nothing about the query.
  const ok = attempts.filter((a) => !a.error && !a.fromCache);
  const [cold, ...warm] = ok;
  const warmMs = median((warm.length ? warm : ok).map(timeOf));
  const flags: StressFlag[] = [];
  if (attempts.some((a) => a.error)) flags.push('error');
  if (warmMs !== null && warmMs > targetMs) flags.push('slow');
  if (ok.some((a) => (a.spillBytes ?? 0) > 0)) flags.push('spill');
  if (ok.some((a) => (a.readBytes ?? 0) >= FULL_SCAN_BYTES && !a.prunedBytes)) flags.push('no_pruning');
  return {
    coldMs: cold ? timeOf(cold) : null,
    warmMs,
    maxMs: ok.length ? Math.max(...ok.map(timeOf)) : null,
    readBytes: cold?.readBytes ?? null,
    rowsRead: cold?.rowsRead ?? null,
    flags,
  };
}
