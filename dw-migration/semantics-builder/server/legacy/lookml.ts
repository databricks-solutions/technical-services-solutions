import type { Explanations } from '../../shared/designer';
import type { FieldStatus, LegacyField } from '../../shared/legacy';
import type { MetricView } from '../../shared/metricView';
import { finish, human, namer, noteOf, quote } from './common';
import type { LegacyResult } from './common';

/**
 * LookML to a metric view, by rules only. A small parser reads views and explores (`key: value`, named blocks,
 * lists, strings, and SQL that ends with `;;`). The base view of the first explore is the source; its joins become
 * joins. ${TABLE}, ${field} and ${view.field} references are replaced; anything with Liquid templating is left for
 * a person.
 */

export interface Pair {
  key: string;
  name?: string;
  value: string | string[] | Pair[];
}

const MAX_DEPTH = 20;
const MAX_PAIRS = 20_000;
const SQL_KEY = /^(sql|sql_\w+|html|expression)$/;

/** Parses LookML text into pairs. Throws a message for the user on a syntax error. */
export function parseLookml(text: string): Pair[] {
  let i = 0;
  let count = 0;
  const fail = (why: string): never => {
    const line = text.slice(0, i).split('\n').length;
    throw new Error(`LookML does not parse at line ${line}: ${why}`);
  };
  const skip = () => {
    for (;;) {
      while (i < text.length && /\s/.test(text[i])) i++;
      if (text[i] !== '#') return;
      while (i < text.length && text[i] !== '\n') i++;
    }
  };
  const word = () => {
    const m = /^[A-Za-z0-9_.+\-:]+/.exec(text.slice(i, i + 300));
    if (!m) fail('a name is missing');
    i += m![0].length;
    return m![0];
  };
  const string = () => {
    let out = '';
    i++;
    while (i < text.length && text[i] !== '"') {
      if (text[i] === '\\' && i + 1 < text.length) i++;
      out += text[i++];
    }
    if (text[i] !== '"') fail('a string does not end');
    i++;
    return out;
  };
  const list = (): string[] => {
    i++;
    const items: string[] = [];
    let cur = '';
    while (i < text.length && text[i] !== ']') {
      if (text[i] === '"') cur += `"${string()}"`;
      else if (text[i] === ',') {
        items.push(cur.trim());
        cur = '';
        i++;
      } else cur += text[i++];
    }
    if (text[i] !== ']') fail('a list does not end');
    i++;
    if (cur.trim()) items.push(cur.trim());
    return items;
  };
  const block = (depth: number): Pair[] => {
    if (depth > MAX_DEPTH) fail('it is nested too deep');
    const pairs: Pair[] = [];
    for (;;) {
      skip();
      if (i >= text.length || text[i] === '}') return pairs;
      if (++count > MAX_PAIRS) fail('it is too large');
      const key = /^[A-Za-z_][A-Za-z0-9_]*/.exec(text.slice(i, i + 100))?.[0] ?? fail('a key is missing');
      i += key.length;
      skip();
      if (text[i] !== ':') fail(`":" is missing after ${key}`);
      i++;
      skip();
      if (SQL_KEY.test(key)) {
        const end = text.indexOf(';;', i);
        if (end < 0) fail(`${key} does not end with ;;`);
        pairs.push({ key, value: text.slice(i, end).trim() });
        i = end + 2;
      } else if (text[i] === '"') pairs.push({ key, value: string() });
      else if (text[i] === '[') pairs.push({ key, value: list() });
      else if (text[i] === '{') {
        i++;
        pairs.push({ key, value: block(depth + 1) });
        skip();
        if (text[i++] !== '}') fail(`${key} does not end with }`);
      } else {
        const name = word();
        skip();
        if (text[i] === '{') {
          i++;
          pairs.push({ key, name, value: block(depth + 1) });
          skip();
          if (text[i++] !== '}') fail(`${key} ${name} does not end with }`);
        } else pairs.push({ key, value: name });
      }
    }
  };
  const top = block(0);
  if (i < text.length) fail('there is a } too many');
  return top;
}

const get = (b: Pair[], key: string) => b.find((p) => p.key === key)?.value;
const str = (b: Pair[], key: string) => {
  const v = get(b, key);
  return typeof v === 'string' ? v : undefined;
};
const all = (b: Pair[], key: string) =>
  b.filter((p) => p.key === key && Array.isArray(p.value)) as (Pair & { value: Pair[] })[];
const LIQUID = /\{%|\{\{/;
const TIMEFRAMES: Record<string, string> = {
  date: 'DAY',
  week: 'WEEK',
  month: 'MONTH',
  quarter: 'QUARTER',
  year: 'YEAR',
};

interface Field {
  view: string;
  name: string;
  kind: 'dimension' | 'measure' | 'group';
  block: Pair[];
}

/** One table name with the default catalog.schema for missing parts. null for a derived table. */
function tableOf(b: Pair[], name: string, schema: string | undefined): string | null {
  const raw = str(b, 'sql_table_name')?.replace(/[`"]/g, '').trim();
  if (!raw) return get(b, 'derived_table') ? null : schema ? `${schema}.${name}` : null;
  const parts = raw.split('.');
  if (parts.length === 3) return raw;
  if (!schema) return null;
  const [catalog] = schema.split('.');
  return parts.length === 2 ? `${catalog}.${raw}` : `${schema}.${raw}`;
}

export function convertLookml(fileName: string, content: string, schema?: string): LegacyResult {
  const top = parseLookml(content);
  const views = new Map(all(top, 'view').map((v) => [v.name!, v.value]));
  if (!views.size)
    throw new Error('The file has no view. Upload the .view.lkml files, and the model with the explore.');
  const explore = all(top, 'explore')[0];
  const issues: string[] = [];
  const fields: LegacyField[] = [];
  const explanations: Explanations = { summary: '', measures: {}, dimensions: {} };

  // The source: the view of the first explore (from: names it when the explore has another name).
  const countMeasures = (b: Pair[]) => b.filter((p) => p.key === 'measure').length;
  const baseName = explore
    ? (str(explore.value, 'from') ?? str(explore.value, 'view_name') ?? explore.name!)
    : [...views.entries()].sort((a, b) => countMeasures(b[1]) - countMeasures(a[1]))[0][0];
  const base = views.get(baseName);
  const empty = (why: string): LegacyResult => ({
    preview: { format: 'lookml', yaml: null, fields: [], sources: [], issues: [why] },
    view: null,
    explanations,
  });
  if (!base) return empty(`The view ${baseName} of the explore is not in the files.`);
  const baseTable = tableOf(base, baseName, schema);
  if (!baseTable)
    return empty(`${baseName} has a derived table or a short table name. Type the catalog.schema of the tables.`);

  // Joined views: the alias is the join name; from: or view_label can point to another view.
  const alias = new Map<string, string>([[baseName, baseName]]);
  const joins: NonNullable<MetricView['joins']> = [];
  const pending: { name: string; on: string; relationship?: string }[] = [];
  for (const j of explore ? all(explore.value, 'join') : []) {
    const viewName = str(j.value, 'from') ?? j.name!;
    const v = views.get(viewName);
    const on = str(j.value, 'sql_on');
    if (!v) {
      issues.push(`The joined view ${viewName} is not in the files.`);
      continue;
    }
    const table = tableOf(v, viewName, schema);
    if (!table || !on) {
      issues.push(`The join ${j.name} has a derived table or no sql_on (foreign_key joins are not converted).`);
      continue;
    }
    alias.set(j.name!, viewName);
    pending.push({ name: j.name!, on, relationship: str(j.value, 'relationship') });
    joins.push({ name: j.name!, source: table, on: '' });
  }

  // Every field of the views in the explore, by alias.
  const fieldsOf = new Map<string, Map<string, Field>>();
  for (const [a, v] of alias) {
    const m = new Map<string, Field>();
    for (const p of views.get(v)!)
      if (
        Array.isArray(p.value) &&
        p.name &&
        (p.key === 'dimension' || p.key === 'measure' || p.key === 'dimension_group')
      )
        m.set(p.name, {
          view: a,
          name: p.name,
          kind: p.key === 'dimension_group' ? 'group' : p.key,
          block: p.value as Pair[],
        });
    fieldsOf.set(a, m);
  }

  const measureNames = new Map<string, string>();
  /** The SQL of a field reference, as the metric view sees it. null when it cannot be placed. */
  const resolve = (sql: string, a: string, depth = 0, keepSource = false): string | null => {
    if (depth > 10 || LIQUID.test(sql)) return null;
    let ok = true;
    const prefix = a === baseName ? '' : `${a}.`;
    const out = sql.replace(/\$\{([A-Za-z0-9_.]+)\}/g, (_all, ref: string) => {
      if (ref === 'TABLE') return a === baseName ? 'source' : a;
      const [v, f] = ref.includes('.') ? ref.split('.', 2) : [a, ref];
      const field =
        fieldsOf.get(v)?.get(f) ?? fieldsOf.get(v)?.get(f.replace(/_(raw|time|date|week|month|quarter|year)$/, ''));
      if (!field) {
        ok = false;
        return _all;
      }
      if (field.kind === 'measure') {
        const n = measureNames.get(`${v}.${field.name}`);
        if (!n) ok = false;
        return n ? `MEASURE(${quote(n)})` : _all;
      }
      const inner = resolve(str(field.block, 'sql') ?? `\${TABLE}.${field.name}`, v, depth + 1, keepSource);
      if (inner === null) ok = false;
      return inner ?? _all;
    });
    if (!ok) return null;
    // A column of the base view is written bare in a metric view; ${TABLE}.x became source.x.
    return prefix || keepSource ? out : out.replace(/\bsource\.([A-Za-z_][A-Za-z0-9_]*)/g, '$1');
  };

  pending.forEach((p, k) => {
    // In a join condition, a column of the source table keeps its source. prefix.
    const on = resolve(p.on, baseName, 0, true);
    if (on === null) {
      issues.push(`The join ${p.name} uses a reference that cannot be replaced. Write its condition by hand.`);
      joins[k].on = 'TRUE';
    } else joins[k].on = on;
    if (p.relationship && p.relationship !== 'many_to_one' && p.relationship !== 'one_to_one')
      issues.push(`The join ${p.name} is ${p.relationship}: measures across it can count rows more than once.`);
  });

  const view: MetricView = {
    version: '1.1',
    source: baseTable,
    ...(joins.length ? { joins } : {}),
    dimensions: [],
    measures: [],
  };
  const unique = namer();
  const note = (status: FieldStatus, text: string) => noteOf('LookML', status, text);
  const label = (f: Field) => str(f.block, 'label') ?? human(f.name);
  const describe = (f: Field) => str(f.block, 'description');

  // Dimensions, and one dimension for each date timeframe of a dimension group.
  for (const [a, m] of fieldsOf)
    for (const f of m.values()) {
      // Hidden fields and keys stay usable in references, but a key is not a business dimension.
      if (f.kind === 'measure' || str(f.block, 'hidden') === 'yes' || str(f.block, 'primary_key') === 'yes') continue;
      const sql = str(f.block, 'sql') ?? `\${TABLE}.${f.name}`;
      const source = `${a}.${f.name} (${f.kind === 'group' ? 'dimension_group' : 'dimension'} ${str(f.block, 'type') ?? 'string'}): ${sql}`;
      const expr = resolve(sql, a);
      const add = (name: string, e: string, status: FieldStatus) => {
        view.dimensions.push({ name, expr: e, ...(describe(f) ? { comment: describe(f)! } : {}), synonyms: [f.name] });
        explanations.dimensions[name] = { explanation: note(status, source) };
        fields.push({ name, kind: 'dimension', source, status, note: '' });
      };
      if (f.kind === 'group') {
        const frames = (get(f.block, 'timeframes') as string[] | undefined) ?? ['date', 'month', 'year'];
        const type = str(f.block, 'type') ?? 'time';
        for (const tf of frames.map((x) => x.replace(/"/g, '').trim())) {
          if (!TIMEFRAMES[tf]) continue;
          const name = unique(`${label(f)} ${human(tf)}`);
          if (expr === null || type !== 'time')
            fields.push({
              name,
              kind: 'dimension',
              source,
              status: 'manual',
              note: 'A reference or a group type that has no rule.',
            });
          else add(name, `DATE_TRUNC('${TIMEFRAMES[tf]}', ${expr})`, 'converted');
        }
        continue;
      }
      const name = unique(label(f));
      if (expr === null)
        fields.push({
          name,
          kind: 'dimension',
          source,
          status: 'manual',
          note: 'Liquid, or a reference that cannot be replaced.',
        });
      else add(name, expr, str(f.block, 'type') === 'tier' ? 'review' : 'converted');
    }

  // Measures: plain aggregations first, so type: number measures can refer to them.
  const AGG: Record<string, (e: string, f: Field) => string | null> = {
    count: () => 'COUNT(1)',
    count_distinct: (e) => `COUNT(DISTINCT ${e})`,
    sum: (e) => `SUM(${e})`,
    average: (e) => `AVG(${e})`,
    min: (e) => `MIN(${e})`,
    max: (e) => `MAX(${e})`,
    median: (e) => `MEDIAN(${e})`,
    percentile: (e, f) =>
      `PERCENTILE_CONT(${Number(str(f.block, 'percentile') ?? 50) / 100}) WITHIN GROUP (ORDER BY ${e})`,
  };
  const measures = [...fieldsOf.values()].flatMap((m) => [...m.values()].filter((f) => f.kind === 'measure'));
  measures.sort((x, y) => Number(str(x.block, 'type') === 'number') - Number(str(y.block, 'type') === 'number'));
  for (const f of measures) measureNames.set(`${f.view}.${f.name}`, label(f));
  for (const f of measures) {
    const type = str(f.block, 'type') ?? 'count';
    const sqlText = str(f.block, 'sql');
    const source = `${f.view}.${f.name} (measure ${type}): ${sqlText ?? ''}`;
    const name = unique(label(f));
    measureNames.set(`${f.view}.${f.name}`, name);
    const manual = (why: string) => fields.push({ name, kind: 'measure', source, status: 'manual', note: why });
    let expr: string | null = null;
    let status: FieldStatus = 'converted';
    if (type === 'number') {
      expr = sqlText ? resolve(sqlText, f.view) : null;
      if (expr === null) {
        manual('A number measure with Liquid or a reference that cannot be replaced.');
        continue;
      }
      if (!/MEASURE\(/.test(expr)) status = 'review';
    } else if (AGG[type]) {
      const inner = type === 'count' ? '1' : resolve(sqlText ?? `\${TABLE}.${f.name}`, f.view);
      if (inner === null) {
        manual('Liquid, or a reference that cannot be replaced.');
        continue;
      }
      expr = AGG[type](inner, f);
      // filters: [field: "value"]; only plain values are converted, not Looker filter expressions.
      const filters = (get(f.block, 'filters') as string[] | Pair[] | undefined) ?? [];
      const conds: string[] = [];
      for (const item of filters) {
        const [k, v] =
          typeof item === 'string'
            ? (item.split(':').map((x) => x.trim()) as [string, string])
            : [str(item.value as Pair[], 'field') ?? '', `"${str(item.value as Pair[], 'value') ?? ''}"`];
        const value = /^"([^"%,<>=!-][^"%,]*)"$/.exec(v ?? '')?.[1];
        const col = k ? resolve(`\${${k}}`, f.view) : null;
        if (value === undefined || col === null) {
          expr = null;
          break;
        }
        conds.push(`${col} = '${value.replace(/'/g, "''")}'`);
      }
      if (expr === null) {
        manual('A filter with a Looker filter expression (such as -x, >10 or %x%).');
        continue;
      }
      if (conds.length) expr = `${expr} FILTER (WHERE ${conds.join(' AND ')})`;
      if (type === 'percentile' || f.view !== baseName) status = 'review';
    } else {
      manual(`The measure type ${type} has no rule.`);
      continue;
    }
    view.measures.push({ name, expr, ...(describe(f) ? { comment: describe(f)! } : {}), synonyms: [f.name] });
    explanations.measures[name] = {
      additivity: type === 'number' ? 'ratio' : ['count', 'sum'].includes(type) ? 'additive' : 'non_additive',
      explanation: note(status, source),
    };
    fields.push({ name, kind: 'measure', source, status, note: status === 'review' ? 'Check it with a test.' : '' });
  }
  return finish(
    'lookml',
    'LookML',
    fileName,
    view,
    fields,
    [baseTable, ...joins.map((j) => j.source)],
    issues,
    explanations
  );
}
