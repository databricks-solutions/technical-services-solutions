/** One stress-test query: measures grouped by dimensions of the metric view. No free SQL. */
export interface WorkloadQuery {
  label: string;
  dimensions: string[];
  measures: string[];
  origin: 'test' | 'generated' | 'custom';
}

export interface StressSettings {
  /** Runs per query: the first is cold, the rest warm. */
  repeats: number;
  /** A query slower than this (warm median) is flagged. */
  targetMs: number;
}

export interface StressAttempt {
  statementId?: string;
  wallMs: number;
  error?: string;
  execMs?: number;
  taskMs?: number;
  readBytes?: number;
  prunedBytes?: number;
  rowsRead?: number;
  spillBytes?: number;
  fromCache?: boolean;
}

export type StressFlag = 'error' | 'slow' | 'spill' | 'no_pruning';

export interface StressQueryResult extends WorkloadQuery {
  sql: string;
  attempts: StressAttempt[];
  coldMs: number | null;
  warmMs: number | null;
  maxMs: number | null;
  readBytes: number | null;
  rowsRead: number | null;
  flags: StressFlag[];
  /** Materialization tries only: the materialization the query read, or null for the sources. */
  matched?: string | null;
}

export type StressStatus = 'running' | 'refreshing' | 'stopping' | 'stopped' | 'finished' | 'failed';

export interface StressRun {
  id: string;
  version: number;
  sandboxView: string;
  settings: StressSettings;
  status: StressStatus;
  error: string | null;
  createdBy: string;
  createdAt: string;
  finishedAt: string | null;
  queries: StressQueryResult[];
  /** Set for a materialization try. */
  materialization: MaterializationTry | null;
}

export interface OptimizeView {
  draft: { version: number; name: string; status: 'draft' | 'validated' } | null;
  workload: WorkloadQuery[];
  /** Field names, for adding a query. */
  view: { dimensions: string[]; measures: string[] } | null;
  /** The statements the run executes first, to create the sandbox view. Shown for approval. */
  setup: { sandboxView: string; statements: string[] } | null;
  limits: { maxQueries: number; maxRepeats: number; timeoutSeconds: number };
  latest: StressRun | null;
  /** From the latest finished stress test of the current version. */
  suggestion: MaterializationSuggestion | null;
  latestTry: StressRun | null;
}

export const SCHEDULES = ['every 1 hour', 'every 6 hours', 'every 24 hours'] as const;
export type Schedule = (typeof SCHEDULES)[number];

export interface SuggestedMaterialization {
  name: string;
  type: 'aggregated' | 'unaggregated';
  dimensions: string[];
  measures: string[];
  /** Workload queries this one is meant to serve. */
  queries: string[];
  reason: string;
}

export interface MaterializationSuggestion {
  basedOnRun: string;
  views: SuggestedMaterialization[];
  /** Queries left out, with why. */
  skipped: { label: string; reason: string }[];
  notes: string[];
}

export interface MaterializationTry {
  schedule: Schedule;
  views: SuggestedMaterialization[];
  yaml: string;
  /** The stress run this try compares with. */
  baseRun: string;
  pipelineUrl?: string;
  refreshMs?: number;
  removed?: boolean;
}

export interface TryPlan {
  matView: string;
  yaml: string;
  statements: string[];
}
