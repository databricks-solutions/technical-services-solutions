import { z } from 'zod';

export type DriftKind = 'schema' | 'definition' | 'governance' | 'usage' | 'data';
export type DriftSeverity = 'error' | 'warning' | 'info';
/** Where the user fixes a finding: the paths the app already has. */
export type DriftFix = 'promote' | 'designer' | 'readiness' | 'materialize' | null;

export interface DriftFinding {
  kind: DriftKind;
  severity: DriftSeverity;
  title: string;
  detail: string;
  fix: DriftFix;
}

/** What a check saw, so the next check can tell what changed. No result values. */
export interface DriftSnapshot {
  owner: string | null;
  grants: string[];
  columns: Record<string, Record<string, string>>;
}

export interface DriftCheck {
  id: string;
  target: string;
  findings: DriftFinding[];
  createdBy: string;
  createdAt: string;
}

export interface DriftView {
  target: string | null;
  problem: string | null;
  last: DriftCheck | null;
  history: { id: string; createdAt: string; errors: number; warnings: number }[];
  /** Measure totals that data drift compares with. null when the user has not opted in. */
  baseline: { at: string; by: string; measures: number } | null;
}

export const baselineSchema = z.object({ enable: z.boolean() });
