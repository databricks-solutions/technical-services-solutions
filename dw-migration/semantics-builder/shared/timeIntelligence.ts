import type { MetricView } from './metricView';

export type Grain = 'day' | 'week' | 'month' | 'quarter' | 'year';
export type TimeKind = 'to_date' | 'previous' | 'last_year' | 'growth' | 'rolling';

export const TIME_KINDS: { kind: TimeKind; label: string }[] = [
  { kind: 'to_date', label: 'Year to date' },
  { kind: 'previous', label: 'Previous period' },
  { kind: 'last_year', label: 'Same period last year' },
  { kind: 'growth', label: 'Growth % against the previous period and last year' },
  { kind: 'rolling', label: 'Rolling 3 periods' },
];

const PER_YEAR: Record<Grain, number> = { day: 365, week: 52, month: 12, quarter: 4, year: 1 };
const TRUNC = /^\s*DATE_TRUNC\s*\(\s*'(\w+)'\s*,\s*([\s\S]+)\)\s*$/i;

/** The grain of a date dimension, from DATE_TRUNC, YEAR() or a date column. Null when it is not a date. */
export function grainOf(expr: string, name = ''): Grain | null {
  const t = TRUNC.exec(expr)?.[1].toLowerCase();
  if (t && t in PER_YEAR) return t as Grain;
  if (/^\s*YEAR\s*\(/i.test(expr)) return 'year';
  if (/date|_dt\b|\bday\b|time/i.test(`${name} ${expr}`)) return 'day';
  return null;
}

// Window ranges and offsets take day and month periods only, so weeks, quarters and years are converted.
const SPAN: Record<Grain, [number, 'day' | 'month']> = {
  day: [1, 'day'],
  week: [7, 'day'],
  month: [1, 'month'],
  quarter: [3, 'month'],
  year: [12, 'month'],
};
const span = (n: number, grain: Grain) => `${n * SPAN[grain][0]} ${SPAN[grain][1]}`;

const quote = (n: string) => (/^[A-Za-z_]\w*$/.test(n) ? n : `\`${n.replace(/`/g, '``')}\``);

/**
 * Adds window measures for one measure over one date dimension: year to date, previous period, same period last
 * year, growth % and a rolling window. A YTD measure needs a year dimension, so it is added when there is none.
 * Names that exist already are kept, so a second run adds nothing.
 */
export function addTimeIntelligence(
  view: MetricView,
  input: { measure: string; dimension: string; grain: Grain; kinds: TimeKind[] }
): { view: MetricView; added: string[] } {
  const m = view.measures.find((x) => x.name === input.measure);
  const d = view.dimensions.find((x) => x.name === input.dimension);
  if (!m || !d) return { view, added: [] };
  const { grain } = input;
  const kinds = new Set(input.kinds);
  const taken = new Set([...view.dimensions, ...view.measures].map((f) => f.name.toLowerCase()));
  const dimensions = [...view.dimensions];
  const measures = [...view.measures];
  const added: string[] = [];
  const base = `MEASURE(${quote(m.name)})`;
  const percent = { type: 'percentage' as const };
  const push = (f: MetricView['measures'][number]) => {
    if (taken.has(f.name.toLowerCase())) return;
    taken.add(f.name.toLowerCase());
    measures.push(f);
    added.push(f.name);
  };
  const offset = (n: number) => ({ order: d.name, range: 'current', offset: `-${span(n, grain)}` });

  if (kinds.has('to_date') && grain !== 'year') {
    const column = TRUNC.exec(d.expr)?.[2].trim() ?? d.expr;
    const year =
      dimensions.find((x) => x.name !== d.name && grainOf(x.expr) === 'year' && x.expr.includes(column)) ??
      (() => {
        const y = { name: `${d.name} Year`, expr: `YEAR(${column})` };
        if (taken.has(y.name.toLowerCase())) return undefined;
        taken.add(y.name.toLowerCase());
        dimensions.push(y);
        added.push(y.name);
        return y;
      })();
    if (year)
      push({
        name: `${m.name} YTD`,
        display_name: `${m.display_name ?? m.name} year to date`,
        expr: base,
        format: m.format,
        window: [
          { order: d.name, range: 'cumulative' },
          { order: year.name, range: 'current' },
        ],
      });
  }
  const previous = `${m.name} PP`;
  const lastYear = `${m.name} PY`;
  if (kinds.has('previous') || kinds.has('growth'))
    push({
      name: previous,
      display_name: `${m.display_name ?? m.name} previous ${grain}`,
      expr: base,
      format: m.format,
      window: [offset(1)],
    });
  if ((kinds.has('last_year') || kinds.has('growth')) && grain !== 'year')
    push({
      name: lastYear,
      display_name: `${m.display_name ?? m.name} same ${grain} last year`,
      expr: base,
      format: m.format,
      window: [offset(PER_YEAR[grain])],
    });
  if (kinds.has('growth')) {
    const growth = (other: string, label: string) =>
      push({
        name: `${m.name} ${label} %`,
        display_name: `${m.display_name ?? m.name} growth against ${label === 'PoP' ? `the previous ${grain}` : 'last year'}`,
        expr: `(${base} - MEASURE(${quote(other)})) / NULLIF(MEASURE(${quote(other)}), 0)`,
        format: percent,
      });
    growth(previous, 'PoP');
    if (grain !== 'year') growth(lastYear, 'YoY');
  }
  if (kinds.has('rolling'))
    push({
      name: `${m.name} 3${grain[0].toUpperCase()}`,
      display_name: `${m.display_name ?? m.name}, rolling 3 ${grain}s`,
      expr: base,
      format: m.format,
      window: [{ order: d.name, range: `trailing ${span(3, grain)} inclusive` }],
    });
  return { view: { ...view, dimensions, measures }, added };
}
