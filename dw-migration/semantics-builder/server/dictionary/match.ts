import type { DictionaryEntry } from '../../shared/dictionary';
import type { MetricView, MetricViewIssue } from '../../shared/metricView';
import type { TableProfile } from '../readiness/profile';

type Profile = Pick<TableProfile, 'fullName' | 'columns'>;
export interface ColumnRef {
  table: string;
  column: string;
}
export interface DictionaryMatch {
  entry: DictionaryEntry;
  via: 'source' | 'formula' | 'name';
  columns: ColumnRef[];
}

const short = (fullName: string) => fullName.split('.').pop()!.toLowerCase();
const flat = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, '');

function bySource(e: DictionaryEntry, profiles: Profile[]): ColumnRef[] {
  const parts = (e.source ?? '').split('.').map((p) => p.trim().replace(/`/g, ''));
  if (parts.length < 2) return [];
  const [table, column] = parts.slice(-2).map((p) => p.toLowerCase());
  const p = profiles.find((x) => short(x.fullName) === table);
  const c = p?.columns.find((x) => x.name.toLowerCase() === column);
  return p && c ? [{ table: p.fullName, column: c.name }] : [];
}

function byFormula(e: DictionaryEntry, profiles: Profile[]): ColumnRef[] {
  const out: ColumnRef[] = [];
  for (const token of e.formula?.match(/[A-Za-z_][A-Za-z0-9_]*/g) ?? []) {
    for (const p of profiles) {
      const c = p.columns.find((x) => x.name.toLowerCase() === token.toLowerCase());
      if (c && !out.some((o) => o.table === p.fullName && o.column === c.name))
        out.push({ table: p.fullName, column: c.name });
    }
  }
  return out;
}

function byName(e: DictionaryEntry, profiles: Profile[]): ColumnRef[] {
  const names = [e.name, ...e.synonyms].map(flat).filter((n) => n.length >= 3);
  return profiles.flatMap((p) =>
    p.columns
      .filter((c) => names.includes(flat(c.name.replace(/^[a-z]{1,3}_/i, ''))) || names.includes(flat(c.name)))
      .map((c) => ({ table: p.fullName, column: c.name }))
  );
}

/** Rule-based: the source column first, then the columns a formula names, then column names. No model call. */
export function matchEntries(entries: DictionaryEntry[], profiles: Profile[]) {
  const matched: DictionaryMatch[] = [];
  const unmatched: DictionaryEntry[] = [];
  const terms = entries.filter((e) => e.kind === 'term');
  for (const entry of entries.filter((e) => e.kind !== 'term')) {
    const found =
      (
        [
          ['source', bySource(entry, profiles)],
          ['formula', byFormula(entry, profiles)],
          ['name', byName(entry, profiles)],
        ] as const
      ).find(([, cols]) => cols.length) ?? null;
    if (found) matched.push({ entry, via: found[0], columns: [...found[1]] });
    else unmatched.push(entry);
  }
  // A derived entry (a ratio of other entries) is supported when its formula names a supported entry.
  for (let changed = true; changed; ) {
    changed = false;
    for (const entry of [...unmatched]) {
      const uses = matched.filter(
        (m) =>
          entry.formula &&
          new RegExp(`\\b${m.entry.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'i').test(entry.formula)
      );
      if (!uses.length) continue;
      const columns = uses
        .flatMap((m) => m.columns)
        .filter((c, i, a) => a.findIndex((x) => x.table === c.table && x.column === c.column) === i);
      matched.push({ entry, via: 'formula', columns });
      unmatched.splice(unmatched.indexOf(entry), 1);
      changed = true;
    }
  }
  return { matched, unmatched, terms };
}

/** Comparable form of an expression: no qualifiers, MEASURE() wrappers, backticks, case or spaces. */
const normExpr = (expr: string) => {
  let s = expr.toLowerCase().replace(/`/g, '');
  for (let i = 0; i < 5; i++) s = s.replace(/measure\s*\(([^()]*)\)/g, '$1');
  return s.replace(/\b[a-z_][a-z0-9_]*\s*\.\s*/g, '').replace(/\s+/g, '');
};

/**
 * Certified dictionary entries lock their name and formula: a measure or dimension that is the entry under
 * another spelling, or with another SQL formula, is an error, so it cannot be validated until it matches.
 */
export function certifiedIssues(view: MetricView, entries: DictionaryEntry[]): MetricViewIssue[] {
  const issues: MetricViewIssue[] = [];
  for (const e of entries.filter((x) => x.status === 'certified' && x.kind !== 'term')) {
    const group = e.kind === 'metric' ? 'measures' : 'dimensions';
    const fields = e.kind === 'metric' ? view.measures : view.dimensions;
    const i = fields.findIndex(
      (f) => flat(f.name) === flat(e.name) || (f.display_name && flat(f.display_name) === flat(e.name))
    );
    if (i < 0) continue;
    const f = fields[i];
    if (f.name !== e.name && flat(f.name) === flat(e.name))
      issues.push({
        severity: 'error',
        message: `"${f.name}" is certified in the dictionary. Use the certified name exactly: "${e.name}".`,
        path: [group, i, 'name'],
      });
    if (e.formula && /\(/.test(e.formula) && normExpr(f.expr) !== normExpr(e.formula))
      issues.push({
        severity: 'error',
        message: `"${e.name}" is certified as ${e.formula}. Use the certified formula, or change the dictionary.`,
        path: [group, i, 'expr'],
      });
  }
  return issues;
}

/** What the model gets: matched entries with their columns, then terms, certified first. Quoted as data. */
export function dictionaryContext(entries: DictionaryEntry[], profiles: Profile[], max = 60) {
  const { matched, terms } = matchEntries(entries, profiles);
  const pick = (e: DictionaryEntry, columns?: ColumnRef[]) => ({
    kind: e.kind,
    name: e.name,
    definition: e.definition,
    ...(e.display_name ? { display_name: e.display_name } : {}),
    ...(e.formula ? { formula: e.formula } : {}),
    ...(e.format ? { format: e.format } : {}),
    ...(e.synonyms.length ? { synonyms: e.synonyms } : {}),
    status: e.status,
    ...(columns ? { columns: columns.map((c) => `${c.table}.${c.column}`) } : {}),
  });
  const rank = (e: DictionaryEntry) => (e.status === 'certified' ? 0 : e.status === 'approved' ? 1 : 2);
  return [
    ...matched.sort((a, b) => rank(a.entry) - rank(b.entry)).map((m) => pick(m.entry, m.columns)),
    ...terms.sort((a, b) => rank(a) - rank(b)).map((e) => pick(e)),
  ].slice(0, max);
}

/**
 * Dictionary definitions that describe one column: by table, then lowercase column. Only dimensions: a metric's
 * source column is where its value comes from, not what the column means. Formula matches are skipped too.
 */
export function columnDefinitions(entries: DictionaryEntry[], profiles: Profile[]) {
  const out = new Map<string, Map<string, { text: string; entry: string }>>();
  for (const m of matchEntries(entries, profiles).matched) {
    if (m.entry.kind !== 'dimension' || m.via === 'formula' || m.columns.length !== 1) continue;
    const [{ table, column }] = m.columns;
    const byColumn = out.get(table.toLowerCase()) ?? new Map<string, { text: string; entry: string }>();
    if (!byColumn.has(column.toLowerCase()))
      byColumn.set(column.toLowerCase(), { text: m.entry.definition, entry: m.entry.name });
    out.set(table.toLowerCase(), byColumn);
  }
  return out;
}
