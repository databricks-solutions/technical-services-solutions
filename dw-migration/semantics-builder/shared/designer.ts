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
  origin: 'generated' | 'refined' | 'edited' | 'pattern' | 'template';
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

const testName = z.string().trim().min(1).max(255);
export const saveDraftSchema = z.object({
  baseVersion: z.number().int().positive(),
  yaml: z.string().min(1).max(200_000),
  /** Set by the test editor. Absent: keep the tests of the base version. */
  tests: z
    .array(
      z.object({
        name: z.string().trim().min(1).max(200),
        dimensions: z.array(testName).max(3),
        measures: z.array(testName).min(1).max(4),
      })
    )
    .max(20)
    .optional(),
});

export const AGGREGATIONS = ['SUM', 'COUNT', 'COUNT_DISTINCT', 'AVG', 'MIN', 'MAX'] as const;
export const GRAINS = ['DAY', 'WEEK', 'MONTH', 'QUARTER', 'YEAR'] as const;

/** The SQL expression of a field built in the form: an aggregation for a measure, a date grain for a dimension. */
export function fieldExpr(f: {
  ref: string;
  column: string;
  aggregation?: (typeof AGGREGATIONS)[number];
  grain?: (typeof GRAINS)[number];
}): string {
  const col = `${f.ref}.${/^[A-Za-z_]\w*$/.test(f.column) ? f.column : `\`${f.column.replace(/`/g, '``')}\``}`;
  if (f.aggregation === 'COUNT' && !f.column) return 'COUNT(1)';
  if (f.aggregation === 'COUNT_DISTINCT') return `COUNT(DISTINCT ${col})`;
  if (f.aggregation) return `${f.aggregation}(${col})`;
  return f.grain ? `DATE_TRUNC('${f.grain}', ${col})` : col;
}

export const validateSchema = z.object({ statements: z.array(z.string().min(1).max(200_000)).min(1).max(10) });
