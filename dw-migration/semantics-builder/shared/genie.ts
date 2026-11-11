import { z } from 'zod';
import type { TestCase, TestFilter } from './designer';

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

/** One check of the Genie agent score. fix names the sub-project page to open, such as designer?tab=model. */
export interface AgentCheck {
  id: string;
  label: string;
  status: 'pass' | 'warn' | 'fail';
  detail: string;
  fix: { label: string; path: string } | null;
}

export interface AgentScore {
  score: number;
  /** 80 or more, and at least one benchmark: with no benchmark, the accuracy is not known. */
  ready: boolean;
  checks: AgentCheck[];
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

const bare = (s: string) =>
  s
    .trim()
    .replace(/^`(.*)`$/, '$1')
    .trim()
    .toLowerCase();

/**
 * The parts of a simple Genie query: the dimensions in the SELECT list (the group), and the WHERE filters as
 * dimension = value. Null when the query has a subquery, OR, parentheses, or a condition that is not
 * `dim = 'v'`, `dim [I]LIKE 'v'` (a %v% pattern counts as v) or `dim IS NOT NULL`.
 */
export function queryParts(sql: string, dimensions: string[]): { group: string[]; filters: TestFilter[] } | null {
  const flat = sql.replace(/\s+/g, ' ').trim();
  if ((flat.match(/\bSELECT\b/gi) ?? []).length !== 1) return null;
  const m = /\bSELECT\b(.*?)\bFROM\b.*?(?:\bWHERE\b(.*?))?(?:\bGROUP BY\b|\bORDER BY\b|\bLIMIT\b|;|$)/i.exec(flat);
  if (!m) return null;
  const select = (m[1] ?? '').replace(/MEASURE\s*\(\s*(`[^`]+`|[\w.]+)\s*\)/gi, ' ').toLowerCase();
  const group = dimensions.filter(
    (d) =>
      select.includes(`\`${d.toLowerCase()}\``) ||
      new RegExp(`(^|[^\\w])${d.toLowerCase().replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}($|[^\\w])`).test(select)
  );
  const where = m[2]?.trim();
  if (!where) return { group, filters: [] };
  if (/\bOR\b|[()]/i.test(where.replace(/'(?:[^'\\]|\\.)*'/g, "''"))) return null;
  const filters: TestFilter[] = [];
  for (const c of where.split(/\s+AND\s+/i)) {
    if (/^(`[^`]+`|\w+)\s+IS\s+NOT\s+NULL$/i.test(c.trim())) continue;
    const f = /^(`[^`]+`|\w+)\s*(=|ILIKE|LIKE)\s*'((?:[^'\\]|\\.)*)'$/i.exec(c.trim());
    const dim = f && dimensions.find((d) => d.toLowerCase() === bare(f[1] ?? ''));
    if (!f || !dim) return null;
    let value = (f[3] ?? '').replace(/\\(.)/g, '$1');
    if (f[2] !== '=') {
      value = value.replace(/^%(.*)%$/, '$1');
      if (value.includes('%')) return null;
    }
    filters.push({ dimension: dim, value });
  }
  return { group, filters };
}

/**
 * A test case from a chat answer. One measure, no group, simple filters and one number: a test with the
 * expected value and the filters. Else a test that compares the fields with plain SQL. Null when the SQL uses
 * no measure.
 */
export function testFromAnswer(question: string, a: ChatAnswer): TestCase | null {
  const measures = a.fields.measures.slice(0, 4);
  if (!measures.length) return null;
  const name = question.trim().slice(0, 200);
  const cell = a.table?.columns.length === 1 && a.table.rows.length === 1 ? a.table.rows[0]?.[0] : null;
  const value = cell === null || cell === undefined || cell.trim() === '' ? NaN : Number(cell);
  const parts = a.sql ? queryParts(a.sql, a.fields.dimensions) : null;
  if (measures.length === 1 && parts && !parts.group.length && parts.filters.length <= 5 && Number.isFinite(value))
    return { name, measures, dimensions: [], expect: { value, tolerancePct: 0.5, filters: parts.filters } };
  return { name, measures, dimensions: a.fields.dimensions.slice(0, 3) };
}

/** One change to the space settings that the AI suggests for a wrong benchmark answer. The AI never writes SQL. */
export type TuningChange =
  | { kind: 'instruction'; text: string }
  | { kind: 'example'; question: string; measures: string[]; dimensions: string[] }
  | { kind: 'synonym'; field: string; synonyms: string[] }
  | { kind: 'description'; field: string; text: string };

/** One line for the user: what the change does. */
export function describeChange(c: TuningChange): string {
  switch (c.kind) {
    case 'instruction':
      return `Add the instruction: ${c.text}`;
    case 'description':
      return `Describe ${c.field} as: ${c.text}`;
    case 'synonym':
      return `Add synonyms to ${c.field}: ${c.synonyms.join(', ')}`;
    case 'example':
      return `Add the example "${c.question}": ${[...c.measures, ...c.dimensions].join(', ')}`;
  }
}

export interface Tuning {
  id: string;
  /** The benchmark question that Genie answered wrong. */
  question: string;
  change: TuningChange;
  rationale: string;
  /** trying: the benchmarks run on the changed space. kept: the accuracy went up. reverted: it did not. */
  status: 'proposed' | 'trying' | 'kept' | 'reverted' | 'dismissed' | 'failed';
  beforeCorrect: number | null;
  afterCorrect: number | null;
  numQuestions: number | null;
  error: string | null;
  createdBy: string;
  createdAt: string;
}

/** One benchmark run. It keeps the counts and the assessment of each question only, never values. */
export interface EvalRun {
  id: string;
  status: 'running' | 'done' | 'failed';
  numQuestions: number;
  numCorrect: number;
  numNeedsReview: number;
  results: { question: string; assessment: string }[];
  tuningId: string | null;
  /** The run used the space settings of the current design and kept changes. */
  current: boolean;
  error: string | null;
  createdAt: string;
}

export interface TuningView {
  runs: EvalRun[];
  tunings: Tuning[];
  /** Benchmarks in the space settings. */
  benchmarks: number;
  /** The space has the settings of the current design and kept changes. */
  spaceCurrent: boolean;
}
