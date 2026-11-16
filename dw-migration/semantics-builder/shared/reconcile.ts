import { z } from 'zod';
import type { TestCase } from './designer';

/**
 * Reconcile: compare the totals of a legacy report with the metric view. The user pastes or loads a CSV export of
 * the report (dimension columns and measure columns). The app runs the same grouping on the sandbox view, as the
 * user, and shows each row with the difference. Nothing of it is stored; passing rows can become expected-value tests.
 */

export const MAX_RECONCILE_ROWS = 500;
export const MAX_RECONCILE_DIMENSIONS = 5;
export const MAX_RECONCILE_MEASURES = 10;

const field = z.string().trim().min(1).max(255);
export const reconcileBody = z
  .object({
    dimensions: z.array(field).max(MAX_RECONCILE_DIMENSIONS),
    measures: z.array(field).min(1).max(MAX_RECONCILE_MEASURES),
    rows: z
      .array(
        z.object({
          keys: z.array(z.string().max(500)).max(MAX_RECONCILE_DIMENSIONS),
          values: z.array(z.number().finite().nullable()).max(MAX_RECONCILE_MEASURES),
        })
      )
      .min(1)
      .max(MAX_RECONCILE_ROWS),
    tolerancePct: z.number().min(0).max(100),
  })
  .refine((b) => b.rows.every((r) => r.keys.length === b.dimensions.length && r.values.length === b.measures.length), {
    message: 'Each row needs one value for each column.',
  })
  .refine((b) => b.dimensions.length > 0 || b.rows.length === 1, {
    message: 'With no dimension column, the report has one row: the totals.',
  });
export type ReconcileBody = z.infer<typeof reconcileBody>;

export type ReconcileStatus = 'passed' | 'failed' | 'missing' | 'skipped';

export interface ReconcileCell {
  measure: string;
  expected: number | null;
  actual: number | null;
  /** Difference in percent of the expected value. */
  diffPct: number | null;
  status: ReconcileStatus;
}

export interface ReconcileRow {
  keys: string[];
  cells: ReconcileCell[];
}

export interface ReconcileResult {
  sandboxView: string;
  /** The query that ran on the sandbox view. */
  sql: string;
  rows: ReconcileRow[];
  counts: Record<ReconcileStatus, number>;
  /** Set when the view returned the row limit, so some rows can be missing. */
  truncated: boolean;
}

/** One CSV text to a header and rows. Quotes, and a comma, semicolon or tab delimiter (from the header line). */
export function parseCsv(text: string): { header: string[]; rows: string[][]; delimiter: string } {
  const src = text.replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n');
  const first = src.split('\n').find((l) => l.trim()) ?? '';
  const outside = first.replace(/"[^"]*"/g, '');
  const delimiter = [',', ';', '\t'].sort((a, b) => outside.split(b).length - outside.split(a).length)[0];
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let quoted = false;
  for (let i = 0; i < src.length; i++) {
    const c = src[i];
    if (quoted) {
      if (c === '"' && src[i + 1] === '"') {
        cell += '"';
        i++;
      } else if (c === '"') quoted = false;
      else cell += c;
    } else if (c === '"' && !cell) quoted = true;
    else if (c === delimiter) {
      row.push(cell.trim());
      cell = '';
    } else if (c === '\n') {
      row.push(cell.trim());
      if (row.some((x) => x)) rows.push(row);
      row = [];
      cell = '';
    } else cell += c;
  }
  row.push(cell.trim());
  if (row.some((x) => x)) rows.push(row);
  const [header = [], ...body] = rows;
  return { header, rows: body, delimiter };
}

/**
 * A number of a report: 1,234.5 or 1.234,5 (the last mark is the decimal mark), (12) for -12, currency signs and
 * spaces removed, 12% for 0.12. null for an empty cell; NaN when it is not a number.
 */
export function parseNumber(raw: string, delimiter = ','): number | null {
  let s = raw.trim();
  if (!s || s === '-') return null;
  const percent = s.endsWith('%');
  s = s.replace(/[%\s\u00a0$€£¥]/g, '');
  let sign = 1;
  if (/^\(.*\)$/.test(s)) {
    sign = -1;
    s = s.slice(1, -1);
  }
  if (s.startsWith('-')) {
    sign *= -1;
    s = s.slice(1);
  }
  const comma = s.lastIndexOf(',');
  const dot = s.lastIndexOf('.');
  if (comma >= 0 && dot >= 0) s = comma > dot ? s.replace(/\./g, '').replace(',', '.') : s.replace(/,/g, '');
  else if (comma >= 0) s = /^\d{1,3}(,\d{3})+$/.test(s) ? s.replace(/,/g, '') : s.replace(',', '.');
  else if (dot >= 0 && delimiter === ';' && /^\d{1,3}(\.\d{3})+$/.test(s)) s = s.replace(/\./g, '');
  if (!/^\d*\.?\d+(e[-+]?\d+)?$/i.test(s)) return NaN;
  return (sign * Number(s)) / (percent ? 100 : 1);
}

const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, '');

/** The field of the view that each CSV column names, or null to ignore it. */
export function autoMap(
  header: string[],
  fields: { dimensions: string[]; measures: string[] }
): ({ kind: 'dimension' | 'measure'; name: string } | null)[] {
  return header.map((h) => {
    const d = fields.dimensions.find((x) => norm(x) === norm(h));
    if (d) return { kind: 'dimension', name: d };
    const m = fields.measures.find((x) => norm(x) === norm(h));
    return m ? { kind: 'measure', name: m } : null;
  });
}

/** A key as the view and the report write it: a midnight timestamp as its date, 12.0 as 12. */
export const normalizeKey = (v: string | null) =>
  (v ?? '')
    .trim()
    .replace(/^(\d{4}-\d{2}-\d{2})[ T]00:00:00(\.0+)?Z?$/, '$1')
    .replace(/^(-?\d+)\.0+$/, '$1');

/**
 * The passing cells as expected-value tests, after the existing tests, up to the limit of a version. Each test
 * checks one measure with the row keys as filters.
 */
export function reconcileTests(
  result: ReconcileResult,
  dimensions: string[],
  tolerancePct: number,
  existing: TestCase[],
  limit = 20
): TestCase[] {
  const names = new Set(existing.map((t) => t.name.toLowerCase()));
  const out: TestCase[] = [];
  for (const row of result.rows)
    for (const c of row.cells) {
      if (c.status !== 'passed' || c.expected === null || existing.length + out.length >= limit) continue;
      const where = dimensions.map((d, i) => `${d} = ${row.keys[i]}`).join(', ');
      let name = `Reconcile ${c.measure}${where ? ` (${where})` : ''}`.slice(0, 190);
      for (let i = 2; names.has(name.toLowerCase()); i++) name = `${name.slice(0, 185)} ${i}`;
      names.add(name.toLowerCase());
      out.push({
        name,
        measures: [c.measure],
        dimensions: [],
        expect: {
          value: c.expected,
          tolerancePct,
          filters: dimensions.map((d, i) => ({ dimension: d, value: row.keys[i] })),
        },
      });
    }
  return out;
}
