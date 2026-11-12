import type { Explanations } from '../../shared/designer';
import type { FieldStatus, LegacyField } from '../../shared/legacy';
import type { MetricView } from '../../shared/metricView';
import { finish, human, IDENT, namer, noteOf, quote } from './common';
import type { AiResult } from './common';

/**
 * MicroStrategy schema and application objects, as the REST Modeling API returns them (GET /api/model/tables,
 * /attributes, /facts and /metrics), to a metric view. The file is JSON with those objects in any arrays: each object
 * has information.subType logical_table, attribute, fact or metric. The fact table is the table of the most facts.
 * An attribute whose lookup table is another table joins on its ID form. Metrics convert by rules; the rest can go
 * to the AI, always marked to check. Conditions, transformations and levels other than the report level are left out.
 */

interface Ref {
  objectId?: string;
  name?: string;
}
interface Info extends Ref {
  subType?: string;
  hidden?: boolean;
  description?: string;
}
interface Expr {
  expression?: { text?: string };
  tables?: Ref[];
}
interface Form {
  id?: string;
  name?: string;
  category?: string;
  expressions?: Expr[];
  lookupTable?: Ref;
}
interface MstrObject {
  information: Info;
  physicalTable?: { information?: Info; namespace?: string; tableName?: string };
  forms?: Form[];
  keyForm?: Ref & { id?: string };
  displays?: { reportDisplays?: (Ref & { id?: string })[] };
  expressions?: Expr[];
  expression?: { text?: string };
}

type Tok = { t: 'ref' | 'str' | 'num' | 'op' | 'name' | 'params' | '(' | ')' | ','; v: string };

function tokenize(src: string): Tok[] | null {
  const out: Tok[] = [];
  let i = 0;
  while (i < src.length) {
    const c = src[i];
    if (/\s/.test(c)) i++;
    else if (c === '[') {
      const end = src.indexOf(']', i);
      if (end < 0) return null;
      out.push({ t: 'ref', v: src.slice(i + 1, end) });
      i = end + 1;
    } else if (c === "'" || c === '"') {
      const end = src.indexOf(c, i + 1);
      if (end < 0) return null;
      out.push({ t: 'str', v: src.slice(i + 1, end) });
      i = end + 1;
    } else if (c === '{') {
      // Dimensionality: {~+} and {~} are the report level, the metric view default. Other levels have no rule.
      const end = src.indexOf('}', i);
      if (end < 0 || !/^~\+?$/.test(src.slice(i + 1, end).trim())) return null;
      i = end + 1;
    } else if (/[0-9.]/.test(c)) {
      const m = /^[0-9]*\.?[0-9]+/.exec(src.slice(i));
      if (!m) return null;
      out.push({ t: 'num', v: m[0] });
      i += m[0].length;
    } else if (/[A-Za-z_]/.test(c)) {
      const w = /^[A-Za-z_][A-Za-z0-9_]*/.exec(src.slice(i))![0];
      i += w.length;
      out.push({ t: 'name', v: w });
      // Function parameters, such as Count<Distinct=True>(Customer).
      const p = /^<([^<>]*)>(?=\s*\()/.exec(src.slice(i));
      if (p) {
        out.push({ t: 'params', v: p[1] });
        i += p[0].length;
      }
    } else if ('(),'.includes(c)) {
      out.push({ t: c as '(' | ')' | ',', v: c });
      i++;
    } else {
      // A condition (<[Filter]>) or a transformation (<;[Last Year]>) has no rule.
      if (/^<\s*[[;@]/.test(src.slice(i))) return null;
      const m = /^(<>|<=|>=|[-+*/=<>])/.exec(src.slice(i));
      if (!m) return null;
      out.push({ t: 'op', v: m[0] });
      i += m[0].length;
    }
  }
  return out;
}

const AGG: Record<string, string> = {
  sum: 'SUM',
  avg: 'AVG',
  min: 'MIN',
  max: 'MAX',
  count: 'COUNT',
  median: 'MEDIAN',
  stdev: 'STDDEV',
  stdevp: 'STDDEV_POP',
  var: 'VARIANCE',
  varp: 'VAR_POP',
};
const PASS: Record<string, string> = {
  abs: 'ABS',
  round: 'ROUND',
  ceiling: 'CEIL',
  floor: 'FLOOR',
  power: 'POWER',
  sqrt: 'SQRT',
  ln: 'LN',
  exp: 'EXP',
  upper: 'UPPER',
  lower: 'LOWER',
  trim: 'TRIM',
  length: 'LENGTH',
  concat: 'CONCAT',
};
const WORDS: Record<string, string> = { and: 'AND', or: 'OR', not: 'NOT', null: 'NULL', true: 'TRUE', false: 'FALSE' };

/**
 * A MicroStrategy expression to SQL, by rules. ref(name, inAggregate) gives the SQL of a fact, attribute, metric or
 * column name; in an aggregate a name is a fact or an attribute, outside it a metric. null when a part has no rule.
 */
export function translateMstr(src: string, ref: (name: string, inAggregate: boolean) => string | null): string | null {
  const parsed = tokenize(src);
  if (!parsed?.length) return null;
  const toks: Tok[] = parsed;
  let i = 0;
  let inAgg = 0;
  const fail = (): never => {
    throw new Error('no rule');
  };
  const args = (): string[] => {
    if (toks[i++]?.t !== '(') fail();
    const list: string[] = [];
    for (;;) {
      list.push(expr());
      const t = toks[i++];
      if (t?.t === ')') return list;
      if (t?.t !== ',') fail();
    }
  };
  const call = (name: string): string => {
    const n = name.toLowerCase();
    let distinct = false;
    if (toks[i]?.t === 'params') {
      for (const p of toks[i++].v.split(',')) {
        const [k, v = ''] = p.split('=').map((x) => x.trim().toLowerCase());
        if (k === 'distinct') distinct = v === 'true';
        else if (k !== 'uselookupforattributes') fail();
      }
    }
    if (AGG[n]) {
      inAgg++;
      const a = args();
      inAgg--;
      if (a.length !== 1) fail();
      return `${AGG[n]}(${distinct ? 'DISTINCT ' : ''}${a[0]})`;
    }
    if (distinct) fail();
    const a = args();
    if (PASS[n] && (n === 'concat' || a.length <= 2)) return `${PASS[n]}(${a.join(', ')})`;
    if (n === 'if' && a.length === 3) return `CASE WHEN ${a[0]} THEN ${a[1]} ELSE ${a[2]} END`;
    if (n === 'nulltozero' && a.length === 1) return `COALESCE(${a[0]}, 0)`;
    if (n === 'zerotonull' && a.length === 1) return `NULLIF(${a[0]}, 0)`;
    if (n === 'isnull' && a.length === 1) return `(${a[0]} IS NULL)`;
    if (n === 'isnotnull' && a.length === 1) return `(${a[0]} IS NOT NULL)`;
    return fail();
  };
  function expr(): string {
    const parts: string[] = [];
    while (i < toks.length) {
      const t = toks[i];
      if (t.t === ')' || t.t === ',') break;
      if (t.t === 'name' && (toks[i + 1]?.t === '(' || toks[i + 1]?.t === 'params')) {
        i++;
        parts.push(call(t.v));
      } else if (t.t === 'name' && WORDS[t.v.toLowerCase()]) {
        parts.push(WORDS[t.v.toLowerCase()]);
        i++;
      } else if (t.t === 'name' || t.t === 'ref') {
        parts.push(ref(t.v, inAgg > 0) ?? fail());
        i++;
      } else if (t.t === 'str') {
        parts.push(`'${t.v.replace(/'/g, "''")}'`);
        i++;
      } else if (t.t === 'num' || t.t === 'op') {
        parts.push(t.v);
        i++;
      } else if (t.t === '(') {
        i++;
        parts.push(`(${expr()})`);
        if (toks[i++]?.t !== ')') fail();
      } else fail();
    }
    if (!parts.length) fail();
    return parts.join(' ');
  }
  try {
    const sql = expr();
    return i === toks.length ? sql : null;
  } catch {
    return null;
  }
}

const aggregates = (sql: string) =>
  /\b(SUM|AVG|MIN|MAX|MEDIAN|COUNT|STDDEV|STDDEV_POP|VARIANCE|VAR_POP|MEASURE)\(/.test(sql);
const slug = (s: string) =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, '_')
    .replace(/^_+|_+$/g, '') || 't';
const KINDS = new Set(['logical_table', 'attribute', 'fact', 'metric']);
const MAX_OBJECTS = 5000;

/** Every MicroStrategy object in the JSON, in any arrays or keys. */
function collect(v: unknown, out: MstrObject[], depth = 0) {
  if (depth > 8 || out.length >= MAX_OBJECTS || !v || typeof v !== 'object') return;
  if (Array.isArray(v)) {
    for (const x of v) collect(x, out, depth + 1);
    return;
  }
  const info = (v as { information?: Info }).information;
  if (info && typeof info === 'object' && KINDS.has(String(info.subType))) {
    out.push(v as MstrObject);
    return;
  }
  for (const x of Object.values(v)) collect(x, out, depth + 1);
}

export const isMicroStrategy = (content: string) =>
  /"subType"\s*:\s*"(attribute|fact|metric|logical_table)"/.test(content) && /"information"\s*:/.test(content);

export function convertMicroStrategy(
  fileName: string,
  content: string,
  schema: string | undefined,
  _base64: boolean,
  ai: Map<string, string> = new Map()
): AiResult {
  let doc: unknown;
  try {
    doc = JSON.parse(content.replace(/^\uFEFF/, ''));
  } catch (err) {
    throw new Error(`The file does not parse as JSON: ${(err as Error).message}`);
  }
  const objects: MstrObject[] = [];
  collect(doc, objects);
  const of = (k: string) => objects.filter((o) => o.information.subType === k && o.information.name);
  const [tables, attributes, facts, metrics] = ['logical_table', 'attribute', 'fact', 'metric'].map(of);
  if (!facts.length && !metrics.length)
    throw new Error('The file has no MicroStrategy facts or metrics. Export them with the REST Modeling API.');

  const issues: string[] = [];
  const fields: LegacyField[] = [];
  const explanations: Explanations = { summary: '', measures: {}, dimensions: {} };
  const todo: AiResult['todo'] = [];
  const empty = (why: string): AiResult => ({
    preview: { format: 'microstrategy', yaml: null, fields: [], sources: [], issues: [why] },
    view: null,
    explanations,
    todo,
    catalog: { columns: [], measures: [] },
  });

  // A table is known by its logical name; a reference can have only the object ID.
  const keyOf = (r?: Ref) =>
    (
      (r?.objectId && tables.find((t) => t.information.objectId === r.objectId)?.information.name) ||
      r?.name ||
      ''
    ).toLowerCase();
  const ucOf = (key: string): string | null => {
    const t = tables.find((x) => x.information.name!.toLowerCase() === key);
    const phys = t?.physicalTable?.tableName ?? t?.physicalTable?.information?.name ?? t?.information.name ?? key;
    const ns = t?.physicalTable?.namespace;
    if (schema) return `${schema}.${phys}`.toLowerCase();
    return ns?.split('.').length === 2 ? `${ns}.${phys}`.toLowerCase() : null;
  };
  const textOn = (exprs: Expr[] | undefined, key: string) =>
    exprs?.find((e) => e.tables?.some((t) => keyOf(t) === key))?.expression?.text ??
    (exprs?.length === 1 && !exprs[0].tables?.length ? exprs[0].expression?.text : undefined);

  // The fact table: the table of the most facts.
  const count = new Map<string, number>();
  for (const f of facts)
    for (const k of new Set((f.expressions ?? []).flatMap((e) => (e.tables ?? []).map(keyOf))))
      if (k) count.set(k, (count.get(k) ?? 0) + 1);
  const factKey = [...count].sort((a, b) => b[1] - a[1])[0]?.[0];
  if (!factKey) return empty('The facts have no tables. Export the facts with their expressions and tables.');
  const factTable = ucOf(factKey);
  if (!factTable) return empty(`${factKey} has no catalog.schema. Type the catalog.schema of the tables.`);
  issues.push(`Tables are mapped by name${schema ? ` to ${schema}` : ''}. Check them.`);

  const alias = new Map<string, string>([[factKey, '']]);
  const columnsOn = (key: string) => (name: string) => {
    const a = alias.get(key);
    const r = IDENT.test(name) ? name.toLowerCase() : quote(name);
    return a === undefined ? null : a ? `${a}.${r}` : r;
  };
  const column = (text: string | undefined, key: string) => (text ? translateMstr(text, columnsOn(key)) : null);
  const wrap = (sql: string) => (/^[\w.`]+$/.test(sql) ? sql : `(${sql})`);

  // Facts: row expressions on the fact table.
  const factSql = new Map<string, string>();
  for (const f of facts) {
    const sql = column(textOn(f.expressions, factKey), factKey);
    if (sql) factSql.set(f.information.name!.toLowerCase(), wrap(sql));
    else
      issues.push(
        `The fact ${f.information.name} is not on ${factKey} or has no rule, so metrics on it need a person.`
      );
  }

  const view: MetricView = { version: '1.1', source: factTable, dimensions: [], measures: [] };
  const joins: NonNullable<MetricView['joins']> = [];
  const unique = namer();
  const note = (status: FieldStatus, t: string) => noteOf('MicroStrategy', status, t);
  // Metric names stay as in the project, because other metrics refer to them.
  for (const m of metrics) unique(m.information.name!);

  // Attributes: the ID form gives the join and the SQL for Count(attribute); the display form is the dimension.
  const attrSql = new Map<string, string>();
  // A join named like a field makes `customer.c_name` read as a field of the dimension Customer.
  const taken = new Set([...attributes, ...metrics].map((o) => o.information.name!.toLowerCase()));
  const joinName = (key: string) => (taken.has(slug(key)) ? `${slug(key)}_table` : slug(key));
  for (const a of attributes) {
    const name = a.information.name!;
    const forms = a.forms ?? [];
    const id =
      forms.find((f) => (a.keyForm?.id && f.id === a.keyForm.id) || (a.keyForm?.name && f.name === a.keyForm.name)) ??
      forms.find((f) => f.category === 'ID') ??
      forms[0];
    if (!id) continue;
    const lookup = keyOf(id.lookupTable) || factKey;
    if (!alias.has(lookup)) {
      const t = ucOf(lookup);
      const fk = textOn(id.expressions, factKey);
      const fkSql = fk ? translateMstr(fk, (n) => `source.${IDENT.test(n) ? n.toLowerCase() : quote(n)}`) : null;
      alias.set(lookup, joinName(lookup));
      const pkSql = column(textOn(id.expressions, lookup), lookup);
      if (!t || !fkSql || !pkSql) {
        alias.delete(lookup);
        issues.push(`${name} does not join ${factKey} on its ID form. Add it as a nested join by hand.`);
        fields.push({
          name,
          kind: 'dimension',
          source: `${name}: lookup table ${lookup}`,
          status: 'manual',
          note: 'Not on the fact table.',
        });
        continue;
      }
      joins.push({ name: alias.get(lookup)!, source: t, on: `${fkSql} = ${pkSql}` });
    }
    const idSql = column(textOn(id.expressions, factKey), factKey) ?? column(textOn(id.expressions, lookup), lookup);
    if (idSql) attrSql.set(name.toLowerCase(), idSql);
    if (a.information.hidden) continue;
    const shown = a.displays?.reportDisplays?.[0];
    const display =
      forms.find((f) => shown && ((shown.id && f.id === shown.id) || (shown.name && f.name === shown.name))) ??
      forms.find((f) => f.category === 'DESC') ??
      id;
    for (const f of [display, ...forms.filter((x) => x !== display && x !== id)]) {
      const key = keyOf(f.lookupTable) || lookup;
      const text = textOn(f.expressions, key);
      const sql = alias.has(key) ? column(text, key) : null;
      const n = unique(f === display ? name : `${name} ${human(f.name ?? 'form')}`);
      const source = `${name} (${f.name ?? 'form'} form): ${text ?? ''} on ${key}`;
      if (!sql) {
        fields.push({ name: n, kind: 'dimension', source, status: 'manual', note: 'A form with no rule.' });
        continue;
      }
      view.dimensions.push({
        name: n,
        expr: sql,
        ...(a.information.description ? { comment: a.information.description } : {}),
      });
      explanations.dimensions[n] = { explanation: note('converted', source) };
      fields.push({ name: n, kind: 'dimension', source, status: 'converted', note: '' });
    }
  }
  if (joins.length) view.joins = joins;

  // Metrics in passes, so a metric can use one that comes later in the file.
  const metricNames = new Set(metrics.map((m) => m.information.name!.toLowerCase()));
  const byLower = new Map(metrics.map((m) => [m.information.name!.toLowerCase(), m.information.name!]));
  const sqlOf = new Map<string, { sql: string; status: FieldStatus }>();
  const ref = (n: string, inAgg: boolean) => {
    const k = n.toLowerCase();
    if (!inAgg && metricNames.has(k)) return sqlOf.has(k) ? `MEASURE(${quote(byLower.get(k)!)})` : null;
    return factSql.get(k) ?? attrSql.get(k) ?? null;
  };
  for (let pass = 0; pass < 3; pass++)
    for (const m of metrics) {
      const k = m.information.name!.toLowerCase();
      if (sqlOf.has(k)) continue;
      const sql = translateMstr(m.expression?.text ?? '', ref);
      if (sql && aggregates(sql)) sqlOf.set(k, { sql, status: 'converted' });
    }
  for (const m of metrics) {
    const k = m.information.name!.toLowerCase();
    if (!sqlOf.has(k) && ai.has(m.information.name!))
      sqlOf.set(k, { sql: ai.get(m.information.name!)!, status: 'review' });
  }
  // A measure must come after the measures it uses: the converted ones go in the order the passes found them.
  const order = [...sqlOf.keys()];
  const rank = (k: string) => (order.includes(k) ? order.indexOf(k) : order.length);
  const sorted = [...metrics].sort(
    (a, b) => rank(a.information.name!.toLowerCase()) - rank(b.information.name!.toLowerCase())
  );
  for (const m of sorted) {
    const name = m.information.name!;
    const text = m.expression?.text ?? '';
    const source = `${name} = ${text}`;
    const r = sqlOf.get(name.toLowerCase());
    if (!r) {
      todo.push({ name, dax: text });
      fields.push({
        name,
        kind: 'measure',
        source,
        status: 'manual',
        note: /<\s*[[;@]/.test(text)
          ? 'A condition or a transformation.'
          : /\{/.test(text)
            ? 'A level other than the report level.'
            : 'An expression with no rule.',
      });
      continue;
    }
    view.measures.push({
      name,
      expr: r.sql,
      ...(m.information.description ? { comment: m.information.description } : {}),
    });
    explanations.measures[name] = {
      additivity:
        /^(SUM|COUNT)\(/.test(r.sql) && !r.sql.includes('DISTINCT')
          ? 'additive'
          : r.sql.includes('/')
            ? 'ratio'
            : 'non_additive',
      explanation: note(r.status, source),
    };
    fields.push({
      name,
      kind: 'measure',
      source,
      status: r.status,
      note: r.status === 'review' ? 'Translated by the AI. Check it with a test.' : '',
    });
  }

  const result = finish(
    'microstrategy',
    'MicroStrategy',
    fileName,
    view,
    fields,
    [factTable, ...joins.map((j) => j.source)],
    issues,
    explanations
  );
  const columns = [
    ...[...factSql].map(([column, sql]) => ({ table: factKey, column, sql })),
    ...[...attrSql].map(([column, sql]) => ({ table: 'attribute', column, sql })),
  ];
  return { ...result, todo, catalog: { columns, measures: [...sqlOf.keys()].map((k) => byLower.get(k)!) } };
}
