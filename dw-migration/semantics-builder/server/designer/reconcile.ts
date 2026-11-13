import { normalizeKey } from '../../shared/reconcile';
import type { ReconcileBody, ReconcileCell, ReconcileResult, ReconcileStatus } from '../../shared/reconcile';
import { quoteId, quoteName } from '../readiness/profile';
import { literal } from './validate';

export const RECONCILE_LIMIT = 20_000;

const NUMBER = /^-?\d+(\.\d+)?$/;

/**
 * The grouping of the report on the metric view: its dimensions as text, its measures, and a filter to the keys of
 * the report, so a large view returns only the rows to compare.
 */
export function reconcileQuery(fullName: string, b: ReconcileBody): string {
  const dims = b.dimensions.map((d) => `CAST(${quoteId(d)} AS STRING) AS ${quoteId(d)}`);
  const measures = b.measures.map((m) => `MEASURE(${quoteId(m)}) AS ${quoteId(m)}`);
  const where = b.dimensions.map((d, i) => {
    const keys = [...new Set(b.rows.map((r) => r.keys[i].trim()))];
    // Numbers compare as numbers, so 12 finds 12.00. Else as text, with a date also as a midnight timestamp.
    if (keys.every((k) => NUMBER.test(k))) return `${quoteId(d)} IN (${keys.join(', ')})`;
    const values = keys.flatMap((k) => (/^\d{4}-\d{2}-\d{2}$/.test(k) ? [k, `${k} 00:00:00`] : [k]));
    return `CAST(${quoteId(d)} AS STRING) IN (${values.map(literal).join(', ')})`;
  });
  return `SELECT ${[...dims, ...measures].join(', ')} FROM ${quoteName(fullName)}${where.length ? ` WHERE ${where.join(' AND ')}` : ''}${dims.length ? ' GROUP BY ALL' : ''} LIMIT ${RECONCILE_LIMIT + 1}`;
}

const toNumber = (v: string | null | undefined) => {
  if (v === null || v === undefined || v.trim() === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

/** Each report row with the view row of the same keys, and each measure with its difference and status. */
export function compareReconcile(
  b: ReconcileBody,
  rows: (string | null)[][]
): Pick<ReconcileResult, 'rows' | 'counts' | 'truncated'> {
  const n = b.dimensions.length;
  const key = (keys: (string | null)[]) => keys.map(normalizeKey).join('\u0000');
  const actual = new Map(rows.slice(0, RECONCILE_LIMIT).map((r) => [key(r.slice(0, n)), r.slice(n)]));
  const counts: Record<ReconcileStatus, number> = { passed: 0, failed: 0, missing: 0, skipped: 0 };
  const out = b.rows.map((row) => {
    const found = actual.get(key(row.keys));
    const cells = b.measures.map((measure, j): ReconcileCell => {
      const expected = row.values[j];
      const value = found ? toNumber(found[j]) : null;
      let cell: ReconcileCell;
      if (expected === null) cell = { measure, expected, actual: value, diffPct: null, status: 'skipped' };
      else if (!found) cell = { measure, expected, actual: null, diffPct: null, status: 'missing' };
      else if (value === null) cell = { measure, expected, actual: null, diffPct: null, status: 'failed' };
      else if (expected === 0)
        cell = { measure, expected, actual: value, diffPct: null, status: value === 0 ? 'passed' : 'failed' };
      else {
        const diffPct = (Math.abs(value - expected) / Math.abs(expected)) * 100;
        cell = {
          measure,
          expected,
          actual: value,
          diffPct,
          status: diffPct <= b.tolerancePct + 1e-9 ? 'passed' : 'failed',
        };
      }
      counts[cell.status]++;
      return cell;
    });
    return { keys: row.keys, cells };
  });
  return { rows: out, counts, truncated: rows.length > RECONCILE_LIMIT };
}
