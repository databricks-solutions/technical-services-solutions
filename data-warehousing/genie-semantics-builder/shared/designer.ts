import { z } from 'zod';
import type { MetricViewIssue } from './metricView';

export type Additivity = 'additive' | 'semi_additive' | 'non_additive' | 'ratio';

export interface Explanations {
  summary: string;
  measures: Record<string, { additivity: Additivity; explanation: string }>;
  dimensions: Record<string, { explanation: string }>;
}

export interface TestCase {
  name: string;
  dimensions: string[];
  measures: string[];
}

export interface DesignDraft {
  version: number;
  name: string;
  yaml: string;
  explanations: Explanations;
  tests: TestCase[];
  issues: MetricViewIssue[];
  origin: 'generated' | 'refined' | 'edited';
  status: 'draft' | 'validated';
  createdBy: string;
  createdAt: string;
}

export interface TestResult {
  name: string;
  status: 'passed' | 'failed' | 'error';
  /** Rows compared. Result values are never stored. */
  rows: number;
  detail: string;
  measureSql: string;
  expandedSql: string | null;
}

export interface ValidationRun {
  id: string;
  version: number;
  status: 'running' | 'passed' | 'failed';
  sandboxView: string;
  results: TestResult[];
  error: string | null;
  /** Approved statement that removes the sandbox view. */
  cleanup: string[];
  createdBy: string;
  createdAt: string;
}

export interface ValidationPlan {
  sandboxView: string;
  statements: string[];
}

export interface DesignerView {
  draft: DesignDraft | null;
  /** Latest validation run of the shown draft. */
  validation: ValidationRun | null;
  history: Pick<DesignDraft, 'version' | 'origin' | 'status' | 'createdBy' | 'createdAt'>[];
}

export const saveDraftSchema = z.object({
  baseVersion: z.number().int().positive(),
  yaml: z.string().min(1).max(200_000),
});

export const validateSchema = z.object({ statements: z.array(z.string().min(1).max(200_000)).min(1).max(10) });
