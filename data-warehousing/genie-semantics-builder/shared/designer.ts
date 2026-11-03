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

export interface DesignerView {
  draft: DesignDraft | null;
  history: Pick<DesignDraft, 'version' | 'origin' | 'status' | 'createdBy' | 'createdAt'>[];
}

export const saveDraftSchema = z.object({
  baseVersion: z.number().int().positive(),
  yaml: z.string().min(1).max(200_000),
});
