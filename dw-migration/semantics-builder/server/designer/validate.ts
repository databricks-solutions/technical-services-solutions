import { UC_NAME_PART } from '../../shared/brief';
import type { Expectation, TestCase, TestResult } from '../../shared/designer';
import { toDirectAliases } from '../../shared/metricView';
import type { Join, MetricView } from '../../shared/metricView';
import { quoteId, quoteName } from '../readiness/profile';

export const MAX_TEST_ROWS = 1000;
const TOLERANCE = 1e-6;

/** The sandbox schema comes from deployment config, never from the request. */
export function sandboxSchema(): string | null {
  const value = process.env.GSB_SANDBOX_SCHEMA?.trim() ?? '';
  const parts = value.split('.');
  return parts.length === 2 && parts.every((p) => UC_NAME_PART.test(p)) ? value : null;
}

/** One sandbox view per project and view name, replaced on every validation. */
export function sandboxViewName(sandbox: string, name: string, projectId: string): string {
  return `${sandbox}.${name}__gsb_${projectId.replace(/-/g, '').slice(0, 8)}`;
}

export function createStatement(fullName: string, yaml: string): string {
  if (yaml.includes('$$')) throw new Error('The YAML cannot contain $$.');
  return `CREATE OR REPLACE VIEW ${quoteName(fullName)} WITH METRICS LANGUAGE YAML AS $$\n${yaml.trimEnd()}\n$$`;
}

export const dropStatement = (fullName: string) => `DROP VIEW IF EXISTS ${quoteName(fullName)}`;

const isTable = (source: string) => /^[^\s()]+$/.test(source.trim());

/** The query a test runs on the metric view. */
export function measureQuery(fullName: string, test: TestCase): string {
  const cols = [
    ...test.dimensions.map(quoteId),
    ...test.measures.map((m) => `MEASURE(${quoteId(m)}) AS ${quoteId(m)}`),
  ];
  return `SELECT ${cols.join(', ')} FROM ${quoteName(fullName)}${test.dimensions.length ? ' GROUP BY ALL' : ''} ORDER BY ALL LIMIT ${MAX_TEST_ROWS + 1}`;
}

const literal = (v: string) => `'${v.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}'`;

/** The query of a test with an expected value: one measure, the filters as WHERE, one row. */
export function expectQuery(fullName: string, test: TestCase): string {
  const where = (test.expect?.filters ?? []).map((f) => `${quoteId(f.dimension)} = ${literal(f.value)}`);
  return `SELECT MEASURE(${quoteId(test.measures[0])}) AS ${quoteId(test.measures[0])} FROM ${quoteName(fullName)}${where.length ? ` WHERE ${where.join(' AND ')}` : ''}`;
}

const pct = (n: number) => `${Number(n.toFixed(2))}%`;

/** Checks the measure value against the expectation. The detail has the difference in percent, never the value. */
export function checkExpected(
  rows: (string | null)[][],
  expect: Expectation
): Pick<TestResult, 'status' | 'rows' | 'detail'> {
  if (rows.length !== 1)
    return { status: 'failed', rows: rows.length, detail: `The query returned ${rows.length} rows, not 1.` };
  const raw = rows[0]?.[0] ?? null;
  const actual = raw === null || raw.trim() === '' ? NaN : Number(raw);
  if (!Number.isFinite(actual)) return { status: 'failed', rows: 1, detail: 'The measure returned no number.' };
  if (expect.value === 0) {
    const ok = actual === 0;
    return {
      status: ok ? 'passed' : 'failed',
      rows: 1,
      detail: ok ? 'Equal to the expected 0.' : 'Not 0 as expected.',
    };
  }
  const diff = (Math.abs(actual - expect.value) / Math.abs(expect.value)) * 100;
  const side = actual > expect.value ? 'above' : 'below';
  return diff <= expect.tolerancePct + 1e-9
    ? {
        status: 'passed',
        rows: 1,
        detail: `Within ${pct(expect.tolerancePct)} of the expected value (difference ${pct(diff)}).`,
      }
    : {
        status: 'failed',
        rows: 1,
        detail: `${pct(diff)} ${side} the expected value. The tolerance is ${pct(expect.tolerancePct)}.`,
      };
}

/**
 * Plain SQL with the same meaning as the test: left joins, composed measures inlined, global filter as WHERE.
 * Null when it cannot be derived: window, partition and OVER () measures.
 */
export function expandedQuery(view: MetricView, test: TestCase): string | null {
  const measures = new Map(view.measures.map((m) => [m.name.toLowerCase(), m]));
  const plain = (m: MetricView['measures'][number]) => !m.window && !m.partition && !/\bOVER\s*\(/i.test(m.expr);
  const dims = new Map(view.dimensions.map((d) => [d.name.toLowerCase(), d]));
  const inline = (expr: string, depth: number): string => {
    if (depth > 10) throw new Error('measure references are too deep');
    return toDirectAliases(
      view,
      expr.replace(/\b(?:MEASURE|AGG)\s*\(\s*(`(?:[^`]|``)+`|[A-Za-z_]\w*)\s*\)/gi, (_, ref: string) => {
        const key = (ref.startsWith('`') ? ref.slice(1, -1).replace(/``/g, '`') : ref).toLowerCase();
        const m = measures.get(key);
        if (!m || !plain(m)) throw new Error(`cannot inline ${ref}`);
        return `(${inline(m.expr, depth + 1)})`;
      })
    );
  };
  try {
    const cols = [
      ...test.dimensions.map((d) => `(${toDirectAliases(view, dims.get(d.toLowerCase())!.expr)}) AS ${quoteId(d)}`),
      ...test.measures.map((name) => {
        const m = measures.get(name.toLowerCase())!;
        if (!plain(m)) throw new Error('not plain SQL');
        return `(${inline(m.expr, 0)}) AS ${quoteId(name)}`;
      }),
    ];
    const joins: string[] = [];
    const walk = (list: Join[] | undefined) =>
      (list ?? []).forEach((j) => {
        const cond = j.on ? `ON ${j.on}` : `USING (${(j.using ?? []).map(quoteId).join(', ')})`;
        joins.push(
          `LEFT JOIN ${isTable(j.source) ? quoteName(j.source) : `(${j.source})`} AS ${quoteId(j.name)} ${cond}`
        );
        walk(j.joins);
      });
    walk(view.joins);
    const from = isTable(view.source) ? quoteName(view.source) : `(${view.source})`;
    return [
      `SELECT ${cols.join(', ')}`,
      `FROM ${from} AS source`,
      ...joins,
      ...(view.filter ? [`WHERE ${toDirectAliases(view, view.filter)}`] : []),
      ...(test.dimensions.length ? ['GROUP BY ALL'] : []),
      `ORDER BY ALL LIMIT ${MAX_TEST_ROWS + 1}`,
    ].join('\n');
  } catch {
    return null;
  }
}

const same = (a: string | null, b: string | null) => {
  if (a === null || b === null) return a === b;
  const x = Number(a);
  const y = Number(b);
  if (a.trim() !== '' && b.trim() !== '' && Number.isFinite(x) && Number.isFinite(y))
    return Math.abs(x - y) <= TOLERANCE * Math.max(1, Math.abs(x), Math.abs(y));
  return a === b;
};

/** Compares two ordered result sets and describes the first difference without its values. */
export function compareRows(
  columns: string[],
  actual: (string | null)[][],
  expected: (string | null)[][],
  against = 'plain SQL'
): Pick<TestResult, 'status' | 'rows' | 'detail'> {
  const rows = Math.min(actual.length, MAX_TEST_ROWS);
  const capped = actual.length > MAX_TEST_ROWS ? ` First ${MAX_TEST_ROWS} rows compared.` : '';
  if (Math.min(actual.length, MAX_TEST_ROWS + 1) !== Math.min(expected.length, MAX_TEST_ROWS + 1))
    return {
      status: 'failed',
      rows,
      detail: `The metric view returned ${actual.length} rows; ${against} has ${expected.length}.`,
    };
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < columns.length; c++) {
      if (!same(actual[r]?.[c] ?? null, expected[r]?.[c] ?? null))
        return { status: 'failed', rows, detail: `Row ${r + 1}, column ${columns[c]} differs from ${against}.` };
    }
  }
  return { status: 'passed', rows, detail: `${rows} rows match ${against}.${capped}` };
}
