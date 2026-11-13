import type { CostRun, StressRun } from '../../shared/optimize';

const PIPELINE_ID = /pipelines\/([0-9a-f-]{36})/;

const median = (xs: number[]) => {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
};

export const seconds = (ms: number) =>
  ms < 60_000 ? `${(ms / 1000).toFixed(1)} s` : `${(ms / 60_000).toFixed(1)} min`;

/** Warehouse use of one run. Cached runs count, at their small cost, so the total is what the app spent. */
export function costOf(run: StressRun, base?: StressRun | null): CostRun {
  const attempts = run.queries.flatMap((q) => q.attempts);
  const out: CostRun = {
    id: run.id,
    kind: run.materialization ? 'try' : 'stress',
    version: run.version,
    status: run.status,
    createdBy: run.createdBy,
    createdAt: run.createdAt,
    statements: attempts.length,
    execMs: attempts.reduce((n, a) => n + (a.execMs ?? a.wallMs), 0),
    taskMs: attempts.reduce((n, a) => n + (a.taskMs ?? 0), 0),
    readBytes: attempts.reduce((n, a) => n + (a.readBytes ?? 0), 0),
    cachedRuns: attempts.filter((a) => a.fromCache).length,
    medianMs: median(run.queries.flatMap((q) => (q.warmMs === null ? [] : [q.warmMs]))),
  };
  const mat = run.materialization;
  if (!mat) return out;
  const matched = run.queries.filter((q) => q.matched);
  const saved = matched.reduce((n, q) => {
    const before = base?.queries.find((b) => b.label === q.label)?.warmMs;
    return before == null || q.warmMs === null ? n : n + (before - q.warmMs);
  }, 0);
  return {
    ...out,
    views: mat.views.map((v) => v.name),
    schedule: mat.schedule,
    refreshMs: mat.refreshMs,
    pipelineId: mat.pipelineUrl?.match(PIPELINE_ID)?.[1],
    matched: matched.length,
    savedMsPerRun: base ? saved : undefined,
  };
}

export const monthStart = (now: Date) => new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1));

export const usedThisMonth = (runs: CostRun[], now = new Date()) =>
  runs.filter((r) => new Date(r.createdAt) >= monthStart(now)).reduce((n, r) => n + r.execMs, 0);

/** Null when the run fits. Otherwise the reason, with the estimate from the average statement this month. */
export function budgetCheck(budgetMs: number | null, usedMs: number, statements: number, avgMs: number) {
  if (budgetMs === null) return null;
  if (usedMs >= budgetMs) return `The monthly budget is used: ${seconds(usedMs)} of ${seconds(budgetMs)}.`;
  const estimate = statements * avgMs;
  const left = budgetMs - usedMs;
  return usedMs + estimate > budgetMs
    ? `This run needs about ${seconds(estimate)}, but ${seconds(left)} of the monthly budget is left. Run fewer queries or raise the budget.`
    : null;
}
