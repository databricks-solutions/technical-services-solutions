import type { AreaScore, Link } from '../../shared/readiness';
import type { ForeignKey, TableProfile } from './profile';

/** What an applied fix changes in a table profile. Stored with each recommendation. */
export interface FixEffect {
  tableComment?: true;
  columns?: string[];
  primaryKey?: string[];
  foreignKey?: ForeignKey;
}

export interface Coverage {
  covered: number;
  total: number;
  missing: string[];
}

export const WEIGHTS = { documentation: 30, keys: 30, types: 15, naming: 10, coverage: 15 } as const;
const TABLE_WEIGHT = WEIGHTS.documentation + WEIGHTS.keys + WEIGHTS.types + WEIGHTS.naming;

const short = (fullName: string) => fullName.split('.').pop()!.toLowerCase();
const KEY = /^(.+?)(_id|_sk|_key|key)$/;

/** `o_custkey` -> `custkey`, `customerID` -> `customer_id`: drops a short table prefix, splits camelCase. */
function stem(column: string) {
  const name = column.replace(/([a-z0-9])([A-Z])/g, '$1_$2').toLowerCase();
  const rest = /^[a-z]{1,3}_(.+)$/.exec(name)?.[1];
  return rest && KEY.test(rest) ? rest : name;
}

/** How well a table name fits a key core: 2 exact, 1 prefix, 0 none. */
function fit(table: string, core: string) {
  const n = short(table);
  if (n === core || n.replace(/s$/, '') === core) return 2;
  // `sales_customers` fits `customer`: a domain prefix before the entity name.
  if (core.length >= 3 && (n.endsWith(`_${core}`) || n.endsWith(`_${core}s`))) return 1;
  return core.length >= 3 && n.startsWith(core) ? 1 : 0;
}

type Columns = Pick<TableProfile, 'fullName' | 'columns'>;

/**
 * Joins suggested by key names, such as `orders.o_custkey` -> `customer.c_custkey` or
 * `events.user_id` -> `users.id`. A column whose own table fits the key best is that table's key.
 */
export function inferLinks(tables: Columns[]): Link[] {
  const out: Link[] = [];
  for (const from of tables) {
    for (const col of from.columns) {
      const s = stem(col.name);
      const core = KEY.exec(s)?.[1];
      if (!core) continue;
      let best: { to: string; refColumn: string; q: number } | null = null;
      for (const to of tables) {
        if (to === from) continue;
        const q = fit(to.fullName, core);
        const ref = to.columns.find((c) => stem(c.name) === s) ?? to.columns.find((c) => c.name.toLowerCase() === 'id');
        if (!q || !ref) continue;
        if (!best || q > best.q || (q === best.q && to.fullName.length < best.to.length))
          best = { to: to.fullName, refColumn: ref.name, q };
      }
      if (best && best.q > fit(from.fullName, core))
        out.push({ from: from.fullName, column: col.name, to: best.to, refColumn: best.refColumn });
    }
  }
  return out;
}

const pct = (n: number, d: number) => (d ? Math.round((100 * n) / d) : 100);
const DATE_NAME = /(date|time|_dt$|_ts$)/i;
const AMOUNT_NAME = /(price|amount|amt|cost|revenue|sales|qty|quantity|discount|tax|total|balance|bal$)/i;
const NUMERIC = /^(tinyint|smallint|int|integer|bigint|long|float|double|decimal|numeric)/i;
const TEMPORAL = /^(date|timestamp)/i;

export function tableAreas(p: TableProfile, project: TableProfile[]): AreaScore[] {
  const n = p.columns.length;
  const commented = p.columns.filter((c) => c.comment).length;
  const documentation = Math.round(30 * (p.comment ? 1 : 0) + 70 * (n ? commented / n : 0));

  const inferred = inferLinks(project).filter((l) => l.from === p.fullName);
  const declaredCols = new Set(p.foreignKeys.flatMap((f) => f.columns.map((c) => c.toLowerCase())));
  const undeclared = inferred.filter((l) => !declaredCols.has(l.column.toLowerCase()));
  const linkTotal = p.foreignKeys.length + undeclared.length;
  const keys = Math.round(
    50 * (p.primaryKey.length ? 1 : 0) + (linkTotal ? (50 * p.foreignKeys.length) / linkTotal : 50)
  );

  const dates = p.columns.filter((c) => DATE_NAME.test(c.name));
  const amounts = p.columns.filter((c) => AMOUNT_NAME.test(c.name) && !DATE_NAME.test(c.name));
  const badTypes = [
    ...dates.filter((c) => !TEMPORAL.test(c.type)),
    ...amounts.filter((c) => !NUMERIC.test(c.type)),
  ].map((c) => c.name);

  const prefixes = new Map<string, number>();
  for (const c of p.columns) {
    const m = /^([a-z]{1,3})_/i.exec(c.name)?.[1].toLowerCase();
    if (m) prefixes.set(m, (prefixes.get(m) ?? 0) + 1);
  }
  const [prefix, count] = [...prefixes].sort((a, b) => b[1] - a[1])[0] ?? ['', 0];
  const shared = n && count / n >= 0.6 ? prefix : '';
  const cryptic = p.columns.filter(
    (c) =>
      (shared && c.name.toLowerCase().startsWith(`${shared}_`)) || (c.name.length <= 2 && c.name.toLowerCase() !== 'id')
  ).length;

  return [
    {
      id: 'documentation',
      label: 'Documentation',
      weight: WEIGHTS.documentation,
      score: documentation,
      detail: `${p.comment ? 'Table has a description' : 'No table description'}; ${commented} of ${n} columns described.`,
    },
    {
      id: 'keys',
      label: 'Keys and relationships',
      weight: WEIGHTS.keys,
      score: keys,
      detail: [
        p.primaryKey.length ? `Primary key ${p.primaryKey.join(', ')}.` : 'No primary key.',
        undeclared.length
          ? `Undeclared joins: ${undeclared.map((l) => `${l.column} -> ${short(l.to)}`).join(', ')}.`
          : p.foreignKeys.length
            ? `${p.foreignKeys.length} foreign key${p.foreignKeys.length === 1 ? '' : 's'} declared.`
            : 'No joins to other project tables found.',
      ].join(' '),
    },
    {
      id: 'types',
      label: 'Data types',
      weight: WEIGHTS.types,
      score: pct(dates.length + amounts.length - badTypes.length, dates.length + amounts.length),
      detail: badTypes.length
        ? `Wrong type for a date or amount: ${badTypes.join(', ')}. Cast them in the metric view source.`
        : 'Dates and amounts use date and numeric types.',
    },
    {
      id: 'naming',
      label: 'Naming clarity',
      weight: WEIGHTS.naming,
      score: pct(n - cryptic, n),
      detail: cryptic
        ? `${cryptic} of ${n} columns use a short prefix or code${shared ? ` (${shared}_)` : ''}. Give the fields business names and synonyms.`
        : 'Column names are readable.',
    },
  ];
}

export const tableScore = (areas: AreaScore[]) =>
  Math.round(areas.reduce((s, a) => s + a.weight * a.score, 0) / TABLE_WEIGHT);

/** Mean of the table areas over the sub-project, plus the coverage of the brief once a brief exists. */
export function projectScore(
  profiles: TableProfile[],
  coverage: (Coverage & { stale?: boolean }) | null
): { score: number; areas: AreaScore[] } {
  const perTable = profiles.map((p) => tableAreas(p, profiles));
  const areas: AreaScore[] = (['documentation', 'keys', 'types', 'naming'] as const).map((id, i) => {
    const scores = perTable.map((a) => a[i]);
    const worst = [...scores].sort((a, b) => a.score - b.score)[0];
    return {
      id,
      label: worst?.label ?? id,
      weight: WEIGHTS[id],
      score: scores.length ? Math.round(scores.reduce((s, a) => s + a.score, 0) / scores.length) : 0,
      detail:
        scores.length > 1 && worst.score < 100
          ? `Average of ${scores.length} tables. Lowest: ${worst.detail}`
          : (worst?.detail ?? ''),
    };
  });
  if (coverage)
    areas.push({
      id: 'coverage',
      label: 'Brief coverage',
      weight: WEIGHTS.coverage,
      score: pct(coverage.covered, coverage.total),
      detail: coverage.stale
        ? 'The brief changed after the last assessment. Assess again to map it to the columns.'
        : coverage.total
          ? coverage.missing.length
            ? `${coverage.covered} of ${coverage.total} measures and dimensions have a source column. Missing: ${coverage.missing.join(', ')}.`
            : `All ${coverage.total} measures and dimensions have a source column.`
          : 'The brief has no measures or dimensions yet.',
    });
  const weight = areas.reduce((s, a) => s + a.weight, 0);
  return { score: Math.round(areas.reduce((s, a) => s + a.weight * a.score, 0) / weight), areas };
}

export function applyEffect(p: TableProfile, e: FixEffect): TableProfile {
  const cols = new Set((e.columns ?? []).map((c) => c.toLowerCase()));
  const fkExists = (f: ForeignKey) =>
    p.foreignKeys.some((x) => x.references === f.references && x.columns.join() === f.columns.join());
  return {
    ...p,
    comment: e.tableComment ? p.comment || 'described' : p.comment,
    columns: p.columns.map((c) => (cols.has(c.name.toLowerCase()) ? { ...c, comment: c.comment || 'described' } : c)),
    primaryKey: e.primaryKey && !p.primaryKey.length ? e.primaryKey : p.primaryKey,
    foreignKeys: e.foreignKey && !fkExists(e.foreignKey) ? [...p.foreignKeys, e.foreignKey] : p.foreignKeys,
  };
}
