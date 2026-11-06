import type { DiscoveredKpi, KpiGroup } from '../../shared/discover';
import { validateMetricView } from '../../shared/metricView';

const AGG = /\b(sum|count|count_if|avg|mean|min|max|median|percentile|approx_count_distinct|stddev|variance|any_value)\s*\(/i;
const STOP = new Set(['total', 'sum', 'of', 'the', 'num', 'number', 'amt', 'amount']);

/** Lower case, no quotes, no table qualifiers, no spaces: `SUM(o.Amount)` and `sum(amount)` are the same. */
export const normalizeExpr = (expr: string) =>
  expr
    .toLowerCase()
    .replace(/`/g, '')
    .replace(/\b[a-z_][a-z0-9_]*\.(?=[a-z_])/g, '')
    .replace(/\s+/g, ' ')
    .replace(/\s*([(),*/+\-<>=])\s*/g, '$1')
    .trim();

/** Words of the name without filler: "Total Revenue", "revenue" and "total_revenue" are the same. */
export const normalizeName = (name: string) => {
  const words = name
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter(Boolean);
  const kept = words.filter((w) => !STOP.has(w));
  return (kept.length ? kept : words).join('_');
};

export function kpisOfMetricView(view: string, yaml: string): DiscoveredKpi[] {
  const parsed = validateMetricView(yaml).view;
  return (parsed?.measures ?? []).map((m) => ({ view, kind: 'metric_view', name: m.name, expr: m.expr }));
}

/** Splits at top-level commas. */
function items(list: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let start = 0;
  let quote: string | null = null;
  for (let i = 0; i < list.length; i++) {
    const c = list[i];
    if (quote) {
      if (c === quote) quote = null;
    } else if (c === "'" || c === '"' || c === '`') quote = c;
    else if (c === '(') depth++;
    else if (c === ')') depth--;
    else if (c === ',' && depth === 0) {
      out.push(list.slice(start, i));
      start = i + 1;
    }
  }
  out.push(list.slice(start));
  return out.map((s) => s.trim()).filter(Boolean);
}

/** The select lists of every SELECT in the SQL, each up to its FROM at the same depth. */
function selectLists(sql: string): string[] {
  const lists: string[] = [];
  const re = /\bselect\b(\s+distinct\b)?/gi;
  for (let m = re.exec(sql); m; m = re.exec(sql)) {
    let depth = 0;
    const from = m.index + m[0].length;
    let end = sql.length;
    for (let i = from; i < sql.length; i++) {
      const c = sql[i];
      if (c === '(') depth++;
      else if (c === ')') {
        if (depth === 0) {
          end = i;
          break;
        }
        depth--;
      } else if (depth === 0 && /^from\b/i.test(sql.slice(i, i + 5)) && /\W/.test(sql[i - 1] ?? ' ')) {
        end = i;
        break;
      }
    }
    lists.push(sql.slice(from, end));
  }
  return lists;
}

/** Aggregations in the select lists of a SQL view, each named by its alias. */
export function kpisOfSqlView(view: string, sql: string): DiscoveredKpi[] {
  const out: DiscoveredKpi[] = [];
  const seen = new Set<string>();
  for (const list of selectLists(sql))
    for (const item of items(list)) {
      if (!AGG.test(item)) continue;
      const m = /^(.*?)(?:\s+as)?\s+`?([A-Za-z_][A-Za-z0-9_]*)`?$/is.exec(item);
      const expr = (m && !/\)$/.test(item) ? m[1] : item).trim();
      const name = m && !/\)$/.test(item) ? m[2] : item;
      if (seen.has(name)) continue;
      seen.add(name);
      out.push({ view, kind: 'sql_view', name, expr });
    }
  return out;
}

/** Groups KPIs of two or more views that share a normalized name or expression, conflicts first. */
export function consolidate(kpis: DiscoveredKpi[]): KpiGroup[] {
  const parent = new Map<string, string>();
  const find = (k: string): string => {
    const p = parent.get(k) ?? k;
    if (p === k) return k;
    const r = find(p);
    parent.set(k, r);
    return r;
  };
  const union = (a: string, b: string) => parent.set(find(a), find(b));
  for (const k of kpis) union(`n:${normalizeName(k.name)}`, `e:${normalizeExpr(k.expr)}`);

  const groups = new Map<string, DiscoveredKpi[]>();
  for (const k of kpis) {
    const root = find(`n:${normalizeName(k.name)}`);
    groups.set(root, [...(groups.get(root) ?? []), k]);
  }

  const out: KpiGroup[] = [];
  for (const members of groups.values()) {
    const views = new Set(members.map((k) => k.view));
    if (views.size < 2) continue;
    const byName = new Map<string, Set<string>>();
    for (const k of members)
      byName.set(normalizeName(k.name), (byName.get(normalizeName(k.name)) ?? new Set()).add(normalizeExpr(k.expr)));
    const conflict = [...byName.values()].some((s) => s.size > 1);
    const count = new Map<string, number>();
    for (const k of members) count.set(normalizeExpr(k.expr), (count.get(normalizeExpr(k.expr)) ?? 0) + 1);
    const canonical = [...members].sort(
      (a, b) =>
        (count.get(normalizeExpr(b.expr)) ?? 0) - (count.get(normalizeExpr(a.expr)) ?? 0) ||
        Number(b.kind === 'metric_view') - Number(a.kind === 'metric_view') ||
        a.view.localeCompare(b.view)
    )[0];
    out.push({
      kpis: members,
      conflict,
      canonical,
      replaces: [...views].filter((v) => v !== canonical.view).sort(),
    });
  }
  return out.sort(
    (a, b) => Number(b.conflict) - Number(a.conflict) || a.canonical.name.localeCompare(b.canonical.name)
  );
}
