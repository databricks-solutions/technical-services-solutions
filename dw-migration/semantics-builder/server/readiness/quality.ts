import type { ReadinessCheck } from '../../shared/readiness';
import type { StatementResult } from '../sql/runner';
import type { TableProfile } from './profile';
import { quoteId, quoteName } from './profile';

export const MAX_CHECK_COLUMNS = 60;
export const HISTORY_ROWS = 50;
const STALE_DAYS = 30;
const MOSTLY_NULL = 0.5;
const TEXT = /^(string|varchar|char)/i;
// approx_count_distinct does not take these types.
const NO_DISTINCT = /^(map|array|struct|variant|binary|geography|geometry)/i;
// History operations that change the data. Maintenance (VACUUM, OPTIMIZE) and metadata changes do not count.
const DATA_WRITE = /WRITE|MERGE|UPDATE|DELETE|AS SELECT|COPY INTO|TRUNCATE|REPLACE|RESTORE|CLONE/i;

const columnsOf = (p: TableProfile) => p.columns.slice(0, MAX_CHECK_COLUMNS);
const pct = (n: number, d: number) => `${Math.round((1000 * n) / d) / 10}%`;
const list = (items: string[]) =>
  items.length > 8 ? `${items.slice(0, 8).join(', ')} and ${items.length - 8} more` : items.join(', ');

/** One full scan: the row count, and for each column the nulls, the empty strings and the distinct count. */
export function qualityQuery(p: TableProfile): string {
  const parts = ['count(*) AS n'];
  columnsOf(p).forEach((c, i) => {
    const col = quoteId(c.name);
    parts.push(`count_if(${col} IS NULL) AS n${i}`);
    if (TEXT.test(c.type)) parts.push(`count_if(trim(${col}) = '') AS e${i}`);
    if (!NO_DISTINCT.test(c.type)) parts.push(`approx_count_distinct(${col}) AS d${i}`);
  });
  return `SELECT ${parts.join(', ')} FROM ${quoteName(p.fullName)}`;
}

export const historyQuery = (p: TableProfile) => `DESCRIBE HISTORY ${quoteName(p.fullName)} LIMIT ${HISTORY_ROWS}`;

/** The time of the last data change in the history, newest first. null when no entry changed the data. */
export function lastWrite(history: StatementResult): Date | null {
  const op = history.columns.indexOf('operation');
  const ts = history.columns.indexOf('timestamp');
  const row = history.rows.find((r) => DATA_WRITE.test(r[op] ?? ''));
  const at = row?.[ts] ? new Date(row[ts]) : null;
  return at && !Number.isNaN(at.getTime()) ? at : null;
}

/**
 * The data checks from the counts. They keep only counts, shares and column names, never a value of the data.
 * lastChange is undefined when the table has no history (a view, or not a Delta table).
 */
export function dataChecks(
  p: TableProfile,
  counts: StatementResult,
  lastChange: Date | null | undefined,
  now = new Date()
): ReadinessCheck[] {
  const row = counts.rows[0] ?? [];
  const num = (name: string) => {
    const i = counts.columns.indexOf(name);
    return i < 0 || row[i] === null ? null : Number(row[i]);
  };
  const n = num('n') ?? 0;
  const cols = columnsOf(p);
  const skipped = p.columns.length - cols.length;
  const stat = (i: number) => ({
    name: cols[i].name,
    nulls: num(`n${i}`) ?? 0,
    empty: num(`e${i}`),
    distinct: num(`d${i}`),
  });
  const stats = cols.map((_, i) => stat(i));
  const allNull = stats.filter((s) => n > 0 && s.nulls === n);
  const mostlyNull = stats.filter((s) => s.nulls < n && s.nulls / n > MOSTLY_NULL);
  const keys = new Set(p.primaryKey.map((k) => k.toLowerCase()));
  const nullKeys = stats.filter((s) => keys.has(s.name.toLowerCase()) && s.nulls > 0);
  const empty = stats.filter((s) => (s.empty ?? 0) > 0);
  const constant = stats.filter((s) => n > 1 && s.distinct === 1 && s.nulls === 0);
  const days = lastChange ? Math.floor((now.getTime() - lastChange.getTime()) / 86_400_000) : null;
  const scope = skipped ? ` The first ${cols.length} columns only; ${skipped} not checked.` : '';

  return [
    {
      id: 'rows',
      label: 'The table has rows',
      status: n > 0 ? 'pass' : 'fail',
      detail: n > 0 ? `${n.toLocaleString('en-US')} rows.` : 'The table is empty.',
    },
    {
      id: 'freshness',
      label: `The data changed in the last ${STALE_DAYS} days`,
      status: days !== null && days <= STALE_DAYS ? 'pass' : 'warn',
      detail:
        lastChange === undefined
          ? 'No table history: a view, or not a Delta table. Check the freshness of its sources.'
          : lastChange === null
            ? `No data change in the last ${HISTORY_ROWS} history entries.`
            : `Last data change on ${lastChange.toISOString().slice(0, 10)}, ${days} days ago.`,
    },
    {
      id: 'key_nulls',
      label: 'Key columns have no nulls',
      status: nullKeys.length ? 'fail' : p.primaryKey.length ? 'pass' : 'warn',
      detail: nullKeys.length
        ? `Nulls in ${nullKeys.map((s) => `${s.name} (${pct(s.nulls, n)})`).join(', ')}.`
        : p.primaryKey.length
          ? `No nulls in ${p.primaryKey.join(', ')}.`
          : 'No primary key is declared, so the key is not checked.',
    },
    {
      id: 'nulls',
      label: 'Columns have values',
      status: allNull.length ? 'fail' : mostlyNull.length ? 'warn' : 'pass',
      detail:
        [
          allNull.length ? `Always null: ${list(allNull.map((s) => s.name))}.` : '',
          mostlyNull.length
            ? `More than half null: ${list(mostlyNull.map((s) => `${s.name} (${pct(s.nulls, n)})`))}.`
            : '',
        ]
          .filter(Boolean)
          .join(' ') || `No column is more than half null.${scope}`,
    },
    {
      id: 'empty_strings',
      label: 'Text columns have no empty strings',
      status: empty.length ? 'warn' : 'pass',
      detail: empty.length
        ? `Empty or blank text in ${list(empty.map((s) => `${s.name} (${pct(s.empty!, n)})`))}. Use null for no value.`
        : `No empty strings.${scope}`,
    },
    {
      id: 'constant',
      label: 'Columns are not constant',
      status: constant.length ? 'warn' : 'pass',
      detail: constant.length
        ? `The same value in each row: ${list(constant.map((s) => s.name))}. It cannot split a measure.`
        : `No constant columns.${scope}`,
    },
  ];
}
