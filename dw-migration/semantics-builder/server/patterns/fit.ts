import type { Pattern, PatternFit } from '../../shared/patterns';
import type { ColumnProfile, TableProfile } from '../readiness/profile';
import { inferLinks } from '../readiness/score';

const TEMPORAL = /^(date|timestamp)/i;
const NUMERIC = /^(tinyint|smallint|int|integer|bigint|long|float|double|decimal|numeric)/i;
const KEYISH = /(_id|_sk|_key|key)$|^id$/i;
const TEXT = /^(string|varchar|char)/i;

const short = (t: string) => t.split('.').pop()!;
const where = (t: TableProfile, c: ColumnProfile) => `${short(t.fullName)}.${c.name}`;

type Matcher = (tables: TableProfile[], used: Set<string>) => string | null;

/** First column that passes the test and was not used by another role of the same pattern. */
const column =
  (test: (c: ColumnProfile) => boolean, prefer?: RegExp): Matcher =>
  (tables, used) => {
    const all = tables.flatMap((t) => t.columns.filter(test).map((c) => where(t, c)));
    const free = all.filter((c) => !used.has(c));
    const pick = free.find((c) => prefer?.test(c)) ?? free[0];
    return pick ?? null;
  };

const table =
  (test: (t: TableProfile) => boolean): Matcher =>
  (tables) =>
    tables.find(test)?.fullName ?? null;

const has = (t: TableProfile, re: RegExp) => t.columns.some((c) => re.test(c.name));
const temporal = (c: ColumnProfile) => TEMPORAL.test(c.type);
const numeric = (c: ColumnProfile) => NUMERIC.test(c.type) && !KEYISH.test(c.name);
const key = (c: ColumnProfile) => KEYISH.test(c.name);
const label = (c: ColumnProfile) => TEXT.test(c.type) && !/comment|desc|address|phone/i.test(c.name);

/** A table that joins to the same table twice, or a fact with several dates (a role-playing date). */
const rolePlaying: Matcher = (tables) => {
  const links = inferLinks(tables);
  const twice = links.find((l, i) => links.some((m, j) => j !== i && m.from === l.from && m.to === l.to));
  if (twice) return `${short(twice.from)} joins ${short(twice.to)} twice`;
  const dated = tables.find((t) => t.columns.filter(temporal).length >= 2);
  return dated ? `${short(dated.fullName)} has ${dated.columns.filter(temporal).length} dates` : null;
};

const MATCHERS: Record<string, Matcher> = {
  event_date: column(temporal, /\.\w*(order|event|txn|transaction|sale)/i),
  snapshot_date: column(
    (c) => /snapshot|as_of|inv_date|stock_date|balance_date/i.test(c.name) && (temporal(c) || key(c))
  ),
  amount: column(numeric, /price|amount|total|revenue|sales|cost|bal/i),
  balance: column((c) => numeric(c) && /bal|on_hand|inventory|stock/i.test(c.name)),
  numerator: column(numeric, /discount|margin|profit|cost/i),
  denominator: column(numeric, /price|revenue|amount|total|sales/i),
  entity_key: column(key, /cust|user|member|account/i),
  item_key: column(key),
  left_key: column(key),
  right_key: column(key),
  entity: column((c) => key(c) || label(c)),
  group: column(label, /region|nation|segment|category|type|group/i),
  stage_conditions: (tables) => {
    const t = tables.find((x) => x.columns.filter((c) => temporal(c) || /status|flag|stage/i.test(c.name)).length >= 2);
    return t ? `${short(t.fullName)} has stage dates or flags` : null;
  },
  role_keys: rolePlaying,
  dimension_table: rolePlaying,
  history_table: table((t) => has(t, /valid_from|start_date|effective/i) && has(t, /valid_to|end_date|expir/i)),
  rate_table: table((t) => has(t, /rate|fx/i)),
  calendar_table: table((t) => t.columns.some(temporal) && has(t, /week|period|fiscal|quarter/i)),
  budget_table: table((t) => /budget|target|plan|forecast/i.test(short(t.fullName)) || has(t, /budget|target/i)),
  band_table: table((t) => has(t, /lower|min_|_min$|from_/i) && has(t, /upper|max_|_max$|to_/i)),
  bridge_table: (tables) => {
    const links = inferLinks(tables);
    const t = tables.find(
      (x) => !x.columns.some(temporal) && new Set(links.filter((l) => l.from === x.fullName).map((l) => l.to)).size >= 2
    );
    return t?.fullName ?? null;
  },
};

export const hasRule = (role: string) => role in MATCHERS;

export const roleLabel = (role: string) => role.replace(/_/g, ' ');

export function patternFit(pattern: Pattern, tables: TableProfile[]): PatternFit {
  const used = new Set<string>();
  const found: PatternFit['found'] = [];
  const missing: string[] = [];
  for (const r of pattern.roles) {
    const match = MATCHERS[r.name]?.(tables, used) ?? null;
    if (match) {
      used.add(match);
      found.push({ role: r.name, match });
    } else missing.push(r.name);
  }
  const status = !missing.length ? 'fits' : found.length ? 'partial' : 'missing';
  return { slug: pattern.slug, status, found, missing };
}
