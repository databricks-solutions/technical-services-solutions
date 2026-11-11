import { z } from 'zod';
import type { TestCase } from './designer';

export type GenieVerdict = 'matches' | 'different' | 'no_answer' | 'needs_review' | 'error';

export interface GenieExpected {
  measures: string[];
  dimensions: string[];
}

export type GenieEngine = 'space' | 'one';

export interface GenieCheck {
  id: string;
  engine: GenieEngine;
  /** Genie One only: the UC objects it read, and if it searched workspace knowledge snippets. */
  read: { assets: string[]; snippets: boolean } | null;
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
  engine: z.enum(['space', 'one']).default('space'),
});

/** A small result table of a Genie answer. Shown live, never stored. */
export interface GenieTable {
  columns: string[];
  rows: (string | null)[][];
  truncated: boolean;
}

/** One answer in the Genie chat panel. The app stores none of it. */
export interface ChatAnswer {
  /** Genie Agent only: send it back to ask a follow-up in the same conversation. */
  conversationId: string | null;
  text: string;
  sql: string | null;
  /** The fields of the view that the SQL names. */
  fields: GenieExpected;
  table: GenieTable | null;
  read: { assets: string[]; snippets: boolean } | null;
  suggested: string[];
}

export const chatSchema = z.object({
  question: z.string().trim().min(3).max(1000),
  engine: z.enum(['space', 'one']),
  conversationId: z
    .string()
    .regex(/^[\w-]{1,64}$/)
    .optional(),
});

/**
 * A test case from a chat answer. One measure, no group, no other filter and one number: a test with the
 * expected value. Else a test that compares the fields with plain SQL. Null when the SQL uses no measure.
 */
export function testFromAnswer(question: string, a: ChatAnswer): TestCase | null {
  const measures = a.fields.measures.slice(0, 4);
  if (!measures.length) return null;
  const name = question.trim().slice(0, 200);
  const cell = a.table?.columns.length === 1 && a.table.rows.length === 1 ? a.table.rows[0]?.[0] : null;
  const value = cell === null || cell === undefined || cell.trim() === '' ? NaN : Number(cell);
  if (measures.length === 1 && !a.fields.dimensions.length && Number.isFinite(value) && !/\bwhere\b/i.test(a.sql ?? ''))
    return { name, measures, dimensions: [], expect: { value, tolerancePct: 0.5, filters: [] } };
  return { name, measures, dimensions: a.fields.dimensions.slice(0, 3) };
}
