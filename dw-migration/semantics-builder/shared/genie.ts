import { z } from 'zod';

export type GenieVerdict = 'matches' | 'different' | 'no_answer' | 'needs_review' | 'error';

export interface GenieExpected {
  measures: string[];
  dimensions: string[];
}

export interface GenieCheck {
  id: string;
  version: number;
  question: string;
  expected: GenieExpected | null;
  verdict: GenieVerdict;
  detail: string;
  answer: string;
  sql: string | null;
  createdBy: string;
  createdAt: string;
}

export interface GenieView {
  /** The design version the space can be built on: the latest validated one with a sandbox view. */
  version: number | null;
  sandboxView: string | null;
  space: { spaceId: string; view: string; createdAt: string } | null;
  keyQuestions: string[];
  checks: GenieCheck[];
}

const name = z.string().trim().min(1).max(255);
export const askSchema = z.object({
  question: z.string().trim().min(3).max(1000),
  expected: z.object({ measures: z.array(name).max(10), dimensions: z.array(name).max(10) }).nullable(),
});
