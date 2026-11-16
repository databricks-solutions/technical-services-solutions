import type { Explanations } from '../../shared/designer';
import type { FieldStatus, LegacyField } from '../../shared/legacy';
import type { MetricView } from '../../shared/metricView';
import { finish, human, IDENT, namer, noteOf, quote } from './common';
import type { AiResult } from './common';
import { child, findAll, parseXml } from './xml';
import type { XmlNode } from './xml';

/**
 * Cognos Framework Manager (model.xml) to a metric view. The database layer gives the tables (query subjects with a
 * dbQuery), their query items and the relationships; the business layer, when there is one, gives the fields as
 * expressions over the database layer. Dimensional objects (regular and measure dimensions) are not converted.
 */

const nameOf = (n: XmlNode) => child(n, 'name')?.text.trim() ?? '';
const slug = (s: string) =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, '_')
    .replace(/^_+|_+$/g, '') || 't';
const AGG: Record<string, (e: string) => string> = {
  total: (e) => `SUM(${e})`,
  sum: (e) => `SUM(${e})`,
  average: (e) => `AVG(${e})`,
  count: (e) => `COUNT(${e})`,
  countDistinct: (e) => `COUNT(DISTINCT ${e})`,
  minimum: (e) => `MIN(${e})`,
  maximum: (e) => `MAX(${e})`,
  median: (e) => `MEDIAN(${e})`,
};
const FN: Record<string, string> = {
  total: 'SUM',
  average: 'AVG',
  minimum: 'MIN',
  maximum: 'MAX',
  count: 'COUNT',
  median: 'MEDIAN',
  abs: 'ABS',
  round: 'ROUND',
  upper: 'UPPER',
  lower: 'LOWER',
  trim: 'TRIM',
  coalesce: 'COALESCE',
  char_length: 'LENGTH',
};
const WORDS: Record<string, string> = {
  and: 'AND',
  or: 'OR',
  not: 'NOT',
  case: 'CASE',
  when: 'WHEN',
  then: 'THEN',
  else: 'ELSE',
  end: 'END',
  null: 'NULL',
  is: 'IS',
  in: 'IN',
  like: 'LIKE',
  distinct: 'DISTINCT',
};

/**
 * A Cognos expression to SQL, by rules. ref(parts) gives the SQL of [a].[b].[c]. null when a part has no rule, such
 * as a macro (#...#), a prompt, or a function with no SQL form here.
 */
export function translateCognos(src: string, ref: (parts: string[]) => string | null): string | null {
  if (/#|\?[^?]*\?/.test(src)) return null;
  const out: string[] = [];
  let i = 0;
  // if (c) then (a) else (b) becomes CASE WHEN c THEN a ELSE b END. The END goes where the group after ELSE closes,
  // or at the end for an if with no parenthesized else.
  let ifs = 0;
  const elseGroups: number[] = [];
  let depth = 0;
  while (i < src.length) {
    const c = src[i];
    if (/\s/.test(c)) {
      i++;
      continue;
    }
    if (c === '[') {
      const parts: string[] = [];
      while (src[i] === '[') {
        const end = src.indexOf(']', i);
        if (end < 0) return null;
        parts.push(src.slice(i + 1, end));
        i = end + 1;
        if (src[i] === '.' && src[i + 1] === '[') i++;
      }
      const sql = ref(parts);
      if (!sql) return null;
      out.push(sql);
    } else if (c === "'") {
      const end = src.indexOf("'", i + 1);
      if (end < 0) return null;
      out.push(src.slice(i, end + 1));
      i = end + 1;
    } else if (/[0-9.]/.test(c)) {
      const m = /^[0-9]*\.?[0-9]+/.exec(src.slice(i));
      if (!m) return null;
      out.push(m[0]);
      i += m[0].length;
    } else if (/[A-Za-z_]/.test(c)) {
      const w = /^[A-Za-z_][A-Za-z0-9_]*/.exec(src.slice(i))![0];
      i += w.length;
      const lw = w.toLowerCase();
      if (lw === 'if') {
        ifs++;
        out.push('CASE WHEN');
      } else if (lw === 'then') out.push('THEN');
      else if (lw === 'else') out.push('ELSE');
      else if (WORDS[lw]) out.push(WORDS[lw]);
      else if (FN[lw] && /^\s*\(/.test(src.slice(i))) out.push(FN[lw]);
      else return null;
    } else if (c === '(') {
      if (out[out.length - 1] === 'ELSE' && ifs > 0) elseGroups.push(depth);
      depth++;
      out.push('(');
      i++;
    } else if (c === ')') {
      depth--;
      out.push(')');
      i++;
      if (elseGroups[elseGroups.length - 1] === depth) {
        elseGroups.pop();
        out.push('END');
        ifs--;
      }
    } else {
      const m = /^(<>|<=|>=|\|\||[-+*/=<>,])/.exec(src.slice(i));
      if (!m) return null;
      out.push(m[0]);
      i += m[0].length;
    }
  }
  if (depth !== 0) return null;
  for (; ifs > 0; ifs--) out.push('END');
  return out
    .join(' ')
    .replace(/\b(SUM|AVG|MIN|MAX|COUNT|MEDIAN|ABS|ROUND|UPPER|LOWER|TRIM|COALESCE|LENGTH) \(/g, '$1(')
    .replace(/\( /g, '(')
    .replace(/ \)/g, ')')
    .replace(/ ,/g, ',');
}

const aggregates = (sql: string) => /\b(SUM|AVG|MIN|MAX|MEDIAN|COUNT|MEASURE)\(/.test(sql);

interface Subject {
  path: string[];
  node: XmlNode;
  db: boolean;
}

export function convertCognos(
  fileName: string,
  content: string,
  schema: string | undefined,
  _base64: boolean,
  ai: Map<string, string> = new Map()
): AiResult {
  const root = parseXml(content.replace(/^\uFEFF/, ''));
  const issues: string[] = [];
  const fields: LegacyField[] = [];
  const explanations: Explanations = { summary: '', measures: {}, dimensions: {} };
  const todo: AiResult['todo'] = [];
  const empty = (why: string): AiResult => ({
    preview: { format: 'cognos', yaml: null, fields: [], sources: [], issues: [why] },
    view: null,
    explanations,
    todo,
    catalog: { columns: [], measures: [] },
  });

  // Every query subject with the names of its namespaces, such as [Database Layer].[ORDERS].
  const subjects: Subject[] = [];
  const walk = (n: XmlNode, path: string[]) => {
    for (const c of n.children) {
      if (c.tag === 'querySubject')
        subjects.push({ path: [...path, nameOf(c)], node: c, db: !!findAll(c, 'dbQuery').length });
      else walk(c, c.tag === 'namespace' ? [...path, nameOf(c)] : path);
    }
  };
  walk(root, []);
  if (!subjects.length)
    throw new Error('The file has no query subjects. Use the model.xml of a Framework Manager project.');
  if (findAll(root, 'dimension').length)
    issues.push('Dimensional objects (regular and measure dimensions) are left out.');

  const db = subjects.filter((s) => s.db);
  const find = (parts: string[]) => {
    // A reference ends with the query subject, or with the subject and an item.
    const lower = parts.map((p) => p.toLowerCase());
    return subjects.find((s) => {
      const p = s.path.map((x) => x.toLowerCase());
      return lower.length <= p.length && p.slice(-lower.length).join('.') === lower.join('.');
    });
  };

  // Tables: the table in the SQL of each database subject, with the default catalog.schema.
  const tableOf = (s: Subject): string | null => {
    const sql = findAll(s.node, 'sql')[0]?.text ?? '';
    const m = /\bfrom\s+((?:\[[^\]]+\]\.)?[\w."]+)/i.exec(sql);
    const t = m?.[1].replace(/^\[[^\]]+\]\./, '').replace(/"/g, '');
    if (!t || !schema) return null;
    const parts = t.split('.');
    return parts.length === 3
      ? t.toLowerCase()
      : parts.length === 2
        ? `${schema.split('.')[0]}.${t}`.toLowerCase()
        : `${schema}.${t}`.toLowerCase();
  };

  // The fact is on the many side of the most relationships.
  const rels = findAll(root, 'relationship').map((r) => ({
    expr: child(r, 'expression')?.text.trim() ?? '',
    sides: ['left', 'right'].map((k) => ({
      ref: child(child(r, k) ?? r, 'refobj')?.text.trim() ?? '',
      many: child(child(r, k) ?? r, 'maxcard')?.text.trim() === 'many',
    })),
  }));
  const manyCount = new Map<Subject, number>();
  for (const r of rels)
    for (const side of r.sides) {
      const s = find(side.ref.split('].[').map((x) => x.replace(/^\[|\]$/g, '')));
      if (s && side.many) manyCount.set(s, (manyCount.get(s) ?? 0) + 1);
    }
  const fact = [...db].sort((a, b) => (manyCount.get(b) ?? 0) - (manyCount.get(a) ?? 0))[0];
  if (!fact) return empty('The model has no database query subject.');
  const factTable = tableOf(fact);
  if (!factTable) return empty(`${fact.path.join('.')} has no table in its SQL, or no catalog.schema was typed.`);
  issues.push(`Tables are mapped by name to ${schema}. Check them.`);

  const alias = new Map<Subject, string>([[fact, '']]);
  const joins: NonNullable<MetricView['joins']> = [];
  const itemOf = (s: Subject, item: string) =>
    s.node.children.find((c) => c.tag === 'queryItem' && nameOf(c).toLowerCase() === item.toLowerCase());
  const columnSql = (s: Subject, item: string): string | null => {
    const a = alias.get(s);
    const q = itemOf(s, item);
    if (a === undefined || !q) return null;
    const ext = child(q, 'externalName')?.text.trim() ?? item;
    const r = IDENT.test(ext) ? ext.toLowerCase() : quote(ext);
    return a ? `${a}.${r}` : r;
  };
  // A join named like a field makes `customer.c_name` read as a field of the dimension Customer.
  const taken = new Set(
    subjects.flatMap((s) =>
      s.node.children
        .filter((c) => c.tag === 'queryItem' || c.tag === 'calculation')
        .flatMap((c) => [nameOf(c).toLowerCase(), human(nameOf(c).toLowerCase()).toLowerCase()])
    )
  );
  for (const r of rels) {
    const subs = r.sides.map((x) => find(x.ref.split('].[').map((y) => y.replace(/^\[|\]$/g, ''))));
    const other = subs[0] === fact ? subs[1] : subs[1] === fact ? subs[0] : undefined;
    if (!other || alias.has(other)) continue;
    const t = tableOf(other);
    if (!t) continue;
    const a = taken.has(slug(nameOf(other.node))) ? `${slug(nameOf(other.node))}_table` : slug(nameOf(other.node));
    alias.set(other, a);
    const on = translateCognos(r.expr, (parts) => {
      const s = find(parts.slice(0, -1));
      const col = s ? columnSql(s, parts[parts.length - 1]) : null;
      return col && s === fact ? `source.${col}` : col;
    });
    if (!on) {
      issues.push(`The relationship to ${nameOf(other.node)} cannot be read. Write the join by hand.`);
      alias.delete(other);
      continue;
    }
    joins.push({ name: a, source: t, on });
  }

  const view: MetricView = {
    version: '1.1',
    source: factTable,
    ...(joins.length ? { joins } : {}),
    dimensions: [],
    measures: [],
  };
  const unique = namer();
  const note = (status: FieldStatus, t: string) => noteOf('Cognos', status, t);

  // The fields: the business layer when it refers to tables in the view, else the database items.
  const business = subjects.filter((s) => !s.db);
  const items = business.length
    ? business.flatMap((s) =>
        s.node.children
          .filter((c) => c.tag === 'queryItem' || c.tag === 'calculation')
          .map((c) => ({ s, c, expr: child(c, 'expression')?.text.trim() ?? '' }))
      )
    : [...alias.keys()].flatMap((s) =>
        s.node.children
          .filter((c) => c.tag === 'queryItem')
          .map((c) => ({ s, c, expr: `[${s.path.join('].[')}].[${nameOf(c)}]` }))
      );
  const measureNames = new Map<string, string>();
  const ref = (parts: string[]) => {
    const s = find(parts.slice(0, -1));
    if (!s) return null;
    if (s.db) return columnSql(s, parts[parts.length - 1]);
    // A business item: a measure is MEASURE(name), an attribute is its own expression.
    const n = measureNames.get(`${s.path.join('.')}.${parts[parts.length - 1]}`.toLowerCase());
    return n ? `MEASURE(${quote(n)})` : null;
  };
  for (let pass = 0; pass < 2; pass++)
    for (const { s, c, expr } of items) {
      const key = `${s.path.join('.')}.${nameOf(c)}`.toLowerCase();
      if (pass === 1 && fields.some((f) => f.source.startsWith(`${key}:`))) continue;
      const usage = child(c, 'usage')?.text.trim() ?? (c.tag === 'calculation' ? 'fact' : 'attribute');
      if (usage === 'identifier' || child(c, 'hidden')?.text.trim() === 'true') continue;
      const agg = child(c, 'regularAggregate')?.text.trim() ?? 'total';
      const name = nameOf(c);
      const source = `${key}: ${expr} (${usage}${usage === 'fact' ? `, ${agg}` : ''})`;
      let sql = expr ? translateCognos(expr, ref) : null;
      let status: FieldStatus = 'converted';
      if (!sql && usage === 'fact' && ai.has(name)) {
        sql = ai.get(name)!;
        status = 'review';
      }
      if (!sql) {
        if (pass === 1) {
          if (usage === 'fact') todo.push({ name, dax: expr });
          fields.push({
            name,
            kind: usage === 'fact' ? 'measure' : 'dimension',
            source,
            status: 'manual',
            note: 'An expression with no rule.',
          });
        }
        continue;
      }
      if (usage === 'fact') {
        const expr2 = aggregates(sql) ? sql : AGG[agg] ? AGG[agg](sql) : null;
        if (!expr2) continue;
        const n = unique(name.includes('_') ? human(name.toLowerCase()) : name);
        measureNames.set(key, n);
        view.measures.push({ name: n, expr: expr2 });
        explanations.measures[n] = {
          additivity: agg === 'total' || agg === 'count' ? 'additive' : 'non_additive',
          explanation: note(status, source),
        };
        fields.push({
          name: n,
          kind: 'measure',
          source,
          status,
          note: status === 'review' ? 'Translated by the AI. Check it with a test.' : '',
        });
      } else {
        if (aggregates(sql)) continue;
        const n = unique(name.includes('_') ? human(name.toLowerCase()) : name);
        view.dimensions.push({ name: n, expr: sql });
        explanations.dimensions[n] = { explanation: note(status, source) };
        fields.push({ name: n, kind: 'dimension', source, status, note: '' });
      }
    }

  const columns = [...alias.keys()].flatMap((s) =>
    s.node.children
      .filter((c) => c.tag === 'queryItem')
      .flatMap((c) => {
        const sql = columnSql(s, nameOf(c));
        return sql ? [{ table: nameOf(s.node), column: nameOf(c), sql }] : [];
      })
  );
  const result = finish(
    'cognos',
    'Cognos',
    fileName,
    view,
    fields,
    [factTable, ...joins.map((j) => j.source)],
    issues,
    explanations
  );
  return { ...result, todo, catalog: { columns, measures: view.measures.map((m) => m.name) } };
}
