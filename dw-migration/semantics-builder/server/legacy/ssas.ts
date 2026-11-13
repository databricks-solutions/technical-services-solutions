import type { Explanations } from '../../shared/designer';
import type { FieldStatus, LegacyField } from '../../shared/legacy';
import type { MetricView } from '../../shared/metricView';
import { finish, IDENT, namer, noteOf, quote } from './common';
import type { AiResult } from './common';
import { child, parseXml } from './xml';
import type { XmlNode } from './xml';

/**
 * SSAS Multidimensional (ASSL XML) to a metric view, best effort. The input is the .dsv, .dim and .cube files of a
 * project, joined, or one database script (.xmla). The measure group with the most measures gives the fact table;
 * its regular dimensions join on their granularity attribute; their attributes become dimensions. Measures with Sum,
 * Count, Min, Max or DistinctCount convert; semi-additive measures do not. Calculated members of the MDX script
 * convert by rules when they are arithmetic on measures; the rest can go to the AI, always marked to check.
 */

const all = (n: XmlNode, pred: (x: XmlNode) => boolean, out: XmlNode[] = []): XmlNode[] => {
  for (const c of n.children) {
    if (pred(c)) out.push(c);
    all(c, pred, out);
  }
  return out;
};
const txt = (n: XmlNode | undefined, tag: string) => (n ? child(n, tag)?.text.trim() : undefined);
const kids = (n: XmlNode | undefined, tag: string) => n?.children.filter((c) => c.tag === tag) ?? [];
const prop = (n: XmlNode, k: string) => Object.entries(n.attrs).find(([a]) => a === k || a.endsWith(`:${k}`))?.[1];
const slug = (s: string) =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, '_')
    .replace(/^_+|_+$/g, '') || 't';

interface Binding {
  table: string;
  column?: string;
}
/** The column (or row) binding inside an element, such as a KeyColumn or a measure Source. */
const bindingOf = (n: XmlNode | undefined): Binding | null => {
  if (!n) return null;
  const s = [n, ...all(n, (x) => x.tag === 'Source')].find((x) => txt(x, 'TableID'));
  const table = txt(s, 'TableID');
  return table ? { table, column: txt(s, 'ColumnID') } : null;
};
const keyColumns = (attr: XmlNode | undefined) =>
  attr ? kids(child(attr, 'KeyColumns'), 'KeyColumn').map(bindingOf) : [];

type Tok = { t: 'ref' | 'str' | 'num' | 'op' | 'name' | '(' | ')' | ','; v: string; parts?: string[] };

function tokenize(src: string): Tok[] | null {
  const out: Tok[] = [];
  let i = 0;
  while (i < src.length) {
    const c = src[i];
    if (/\s/.test(c)) i++;
    else if (c === '[') {
      const parts: string[] = [];
      while (src[i] === '[') {
        let end = src.indexOf(']', i);
        while (end >= 0 && src[end + 1] === ']') end = src.indexOf(']', end + 2);
        if (end < 0) return null;
        parts.push(src.slice(i + 1, end).replace(/]]/g, ']'));
        i = end + 1;
        if (src[i] === '.' && src[i + 1] === '[') i++;
      }
      // A member function (.PrevMember) or a member key (&[1]) has no rule.
      if (src[i] === '.' || src[i] === '&') return null;
      out.push({ t: 'ref', v: parts.join('.'), parts });
    } else if (c === '"' || c === "'") {
      const end = src.indexOf(c, i + 1);
      if (end < 0) return null;
      out.push({ t: 'str', v: src.slice(i + 1, end) });
      i = end + 1;
    } else if (/[0-9.]/.test(c)) {
      const m = /^[0-9]*\.?[0-9]+/.exec(src.slice(i));
      if (!m) return null;
      out.push({ t: 'num', v: m[0] });
      i += m[0].length;
    } else if (/[A-Za-z_]/.test(c)) {
      const w = /^[A-Za-z_][A-Za-z0-9_]*/.exec(src.slice(i))![0];
      out.push({ t: 'name', v: w });
      i += w.length;
    } else if ('(),'.includes(c)) {
      out.push({ t: c as '(' | ')' | ',', v: c });
      i++;
    } else {
      const m = /^(<>|<=|>=|[-+*/=<>])/.exec(src.slice(i));
      if (!m) return null;
      out.push({ t: 'op', v: m[0] });
      i += m[0].length;
    }
  }
  return out;
}

const WORDS: Record<string, string> = { and: 'AND', or: 'OR', not: 'NOT', null: 'NULL' };

/** An MDX calculated measure to SQL, by rules. measure(name) gives MEASURE(`name`) or null. */
export function translateMdx(src: string, measure: (name: string) => string | null): string | null {
  const parsed = tokenize(src);
  if (!parsed?.length) return null;
  const toks: Tok[] = parsed;
  let i = 0;
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
    const a = args();
    if (n === 'iif' && a.length === 3) return `CASE WHEN ${a[0]} THEN ${a[1]} ELSE ${a[2]} END`;
    if (n === 'isempty' && a.length === 1) return `(${a[0]} IS NULL)`;
    if (n === 'divide' && a.length === 2) return `${a[0]} / NULLIF(${a[1]}, 0)`;
    if (n === 'coalesceempty' && a.length >= 2) return `COALESCE(${a.join(', ')})`;
    if (n === 'abs' && a.length === 1) return `ABS(${a[0]})`;
    if (n === 'round' && a.length <= 2) return `ROUND(${a.join(', ')})`;
    return fail();
  };
  function expr(): string {
    const parts: string[] = [];
    while (i < toks.length) {
      const t = toks[i];
      if (t.t === ')' || t.t === ',') break;
      if (t.t === 'name' && toks[i + 1]?.t === '(') {
        i++;
        parts.push(call(t.v));
      } else if (t.t === 'name' && WORDS[t.v.toLowerCase()]) {
        parts.push(WORDS[t.v.toLowerCase()]);
        i++;
      } else if (t.t === 'ref') {
        const p = t.parts!;
        const name = p.length === 2 && p[0].toLowerCase() === 'measures' ? p[1] : p.length === 1 ? p[0] : null;
        parts.push((name && measure(name)) ?? fail());
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

/** The calculated measures of an MDX script: CREATE MEMBER CURRENTCUBE.[Measures].[Name] AS expr, props; */
export function calculatedMeasures(script: string): { name: string; expr: string }[] {
  const out: { name: string; expr: string }[] = [];
  const re = /CREATE\s+(?:HIDDEN\s+)?MEMBER\s+CURRENTCUBE\s*\.\s*\[Measures\]\s*\.\s*\[((?:[^\]]|]])+)\]\s+AS\s+/gi;
  for (let m = re.exec(script); m; m = re.exec(script)) {
    let i = re.lastIndex;
    let depth = 0;
    let quote = '';
    const start = i;
    for (; i < script.length; i++) {
      const c = script[i];
      if (quote) {
        if (c === quote) quote = '';
      } else if (c === '"' || c === "'" || c === '[') quote = c === '[' ? ']' : c;
      else if (c === '(') depth++;
      else if (c === ')') depth--;
      else if ((c === ',' || c === ';') && depth === 0) break;
    }
    let expr = script.slice(start, i).trim();
    // The old syntax quotes the whole expression: AS '[Measures].[A] / 2'.
    if (/^'.*'$/s.test(expr)) expr = expr.slice(1, -1).replace(/''/g, "'");
    out.push({ name: m[1].replace(/]]/g, ']'), expr });
    re.lastIndex = i;
  }
  return out;
}

const AGG: Record<string, (e: string) => string> = {
  sum: (e) => `SUM(${e})`,
  count: (e) => `COUNT(${e})`,
  min: (e) => `MIN(${e})`,
  max: (e) => `MAX(${e})`,
  distinctcount: (e) => `COUNT(DISTINCT ${e})`,
};

export const isSsas = (fileName: string, content: string) =>
  /\.(cube|dim|dsv|xmla|ssas)$/i.test(fileName) || (/\.xml$/i.test(fileName) && /<MeasureGroups>/.test(content));

export function convertSsas(
  fileName: string,
  content: string,
  schema: string | undefined,
  _base64: boolean,
  ai: Map<string, string> = new Map()
): AiResult {
  const root = parseXml(content.replace(/\uFEFF/g, ''));
  const issues: string[] = [];
  const fields: LegacyField[] = [];
  const explanations: Explanations = { summary: '', measures: {}, dimensions: {} };
  const todo: AiResult['todo'] = [];
  const empty = (why: string): AiResult => ({
    preview: { format: 'ssas', yaml: null, fields: [], sources: [], issues: [why] },
    view: null,
    explanations,
    todo,
    catalog: { columns: [], measures: [] },
  });

  const cubes = all(root, (n) => n.tag === 'Cube' && !!child(n, 'MeasureGroups'));
  if (!cubes.length)
    throw new Error(
      'The files have no cube. Choose the .dsv, .dim and .cube files of the project, or an .xmla script.'
    );
  const cube = cubes[0];
  if (cubes.length > 1) issues.push(`Only the cube ${txt(cube, 'Name')} is read.`);

  // Data source view tables: the element name is the TableID of the bindings.
  const tables = new Map<
    string,
    { db?: string; query: boolean; columns: Map<string, { db?: string; computed?: string }> }
  >();
  for (const el of all(
    root,
    (n) => /(^|:)element$/.test(n.tag) && !!(prop(n, 'DbTableName') ?? prop(n, 'TableType'))
  )) {
    const columns = new Map<string, { db?: string; computed?: string }>();
    for (const c of all(el, (n) => /(^|:)element$/.test(n.tag) && !!n.attrs.name))
      columns.set(c.attrs.name, { db: prop(c, 'DbColumnName'), computed: prop(c, 'ComputedColumnExpression') });
    tables.set(el.attrs.name, { db: prop(el, 'DbTableName'), query: !!prop(el, 'QueryDefinition'), columns });
  }
  const ucOf = (id: string) => {
    const t = tables.get(id);
    if (!t || t.query || !schema) return null;
    return `${schema}.${t.db ?? id}`.toLowerCase();
  };

  // The fact: the table of the measure group with the most measures.
  const groups = kids(child(cube, 'MeasureGroups'), 'MeasureGroup');
  const mg = [...groups].sort(
    (a, b) => kids(child(b, 'Measures'), 'Measure').length - kids(child(a, 'Measures'), 'Measure').length
  )[0];
  const measureNodes = kids(child(mg, 'Measures'), 'Measure');
  const counts = new Map<string, number>();
  for (const m of measureNodes) {
    const b = bindingOf(child(m, 'Source'));
    if (b) counts.set(b.table, (counts.get(b.table) ?? 0) + 1);
  }
  const factId = [...counts].sort((a, b) => b[1] - a[1])[0]?.[0];
  if (!factId) return empty('The measure group has no measure bound to a table.');
  if (tables.get(factId)?.query)
    return empty(`${factId} is a named query. Make it a table or a view first, then import again.`);
  const factTable = ucOf(factId);
  if (!factTable) return empty(`${factId} is not in the data source view, or no catalog.schema was typed.`);
  issues.push(`Tables are mapped by name to ${schema}. Check them.`);
  for (const g of groups)
    if (g !== mg) issues.push(`The measure group ${txt(g, 'Name')} is left out: a metric view has one fact table.`);

  const alias = new Map<string, string>();
  const colSql = (a: string, table: string, column: string | undefined): string | null => {
    if (!column) return null;
    const c = tables.get(table)?.columns.get(column);
    if (c?.computed) return null;
    const name = c?.db ?? column;
    const r = IDENT.test(name) ? name.toLowerCase() : quote(name);
    return a ? `${a}.${r}` : r;
  };

  const dims = new Map(
    all(
      root,
      (n) =>
        n.tag === 'Dimension' &&
        !child(n, 'DimensionID') &&
        !child(n, 'CubeDimensionID') &&
        !!child(n, 'Attributes') &&
        !!child(n, 'ID')
    ).map((d) => [txt(d, 'ID')!, d])
  );
  const cubeDims = new Map(kids(child(cube, 'Dimensions'), 'Dimension').map((d) => [txt(d, 'ID')!, d]));
  const calcs = all(cube, (n) => n.tag === 'MdxScript').flatMap((s) =>
    calculatedMeasures(
      all(s, (n) => n.tag === 'Text')
        .map((t) => t.text)
        .join('\n')
    )
  );

  const unique = namer();
  const note = (status: FieldStatus, t: string) => noteOf('SSAS', status, t);
  // Measure names stay as in the cube, because calculated members refer to them.
  for (const m of measureNodes) unique(txt(m, 'Name') ?? txt(m, 'ID') ?? 'Measure');
  for (const c of calcs) unique(c.name);
  // A join named like a field makes `product.color` read as a field of the dimension Product.
  const taken = new Set(
    [
      ...measureNodes.map((m) => txt(m, 'Name')),
      ...calcs.map((c) => c.name),
      ...[...dims.values()].flatMap((d) => kids(child(d, 'Attributes'), 'Attribute').map((a) => txt(a, 'Name'))),
    ]
      .filter((x): x is string => !!x)
      .map((x) => x.toLowerCase())
  );
  const usedAliases = new Set<string>();
  const joinName = (s: string) => {
    let a = slug(s);
    if (taken.has(a)) a = `${a}_table`;
    for (let i = 2; usedAliases.has(a); i++) a = `${slug(s)}_${i}`;
    usedAliases.add(a);
    return a;
  };

  const view: MetricView = { version: '1.1', source: factTable, dimensions: [], measures: [] };
  const joins: NonNullable<MetricView['joins']> = [];
  const mgDims = kids(child(mg, 'Dimensions'), 'Dimension');
  const roleCount = new Map<string, number>();
  for (const d of mgDims) {
    const dimId = txt(cubeDims.get(txt(d, 'CubeDimensionID') ?? ''), 'DimensionID') ?? '';
    roleCount.set(dimId, (roleCount.get(dimId) ?? 0) + 1);
  }
  for (const d of mgDims) {
    const cd = cubeDims.get(txt(d, 'CubeDimensionID') ?? '');
    const cdName = txt(cd, 'Name') ?? txt(d, 'CubeDimensionID') ?? 'Dimension';
    const dim = dims.get(txt(cd, 'DimensionID') ?? '');
    const type = (d.attrs['xsi:type'] ?? 'RegularMeasureGroupDimension').replace(/MeasureGroupDimension$/, '');
    if (!dim) {
      issues.push(`The dimension ${cdName} is not in the files. Add its .dim file.`);
      continue;
    }
    const attrs = kids(child(dim, 'Attributes'), 'Attribute');
    const key = attrs.find((a) => txt(a, 'Usage') === 'Key') ?? attrs[0];
    let a = '';
    let dimTable = factId;
    if (type === 'Regular') {
      const mgAttrs = kids(child(d, 'Attributes'), 'Attribute');
      const gran = mgAttrs.find((x) => txt(x, 'Type') === 'Granularity') ?? mgAttrs[0];
      if (!gran || txt(gran, 'AttributeID') !== txt(key, 'ID')) {
        issues.push(`${cdName} joins above its key attribute. Add it by hand.`);
        continue;
      }
      const fk = keyColumns(gran);
      const pk = keyColumns(key);
      dimTable = pk[0]?.table ?? '';
      const t = ucOf(dimTable);
      if (!t || !fk.length || fk.length !== pk.length || fk.some((x) => !x) || pk.some((x) => !x)) {
        issues.push(`${cdName} has no table or no key columns to join on, so it is left out.`);
        continue;
      }
      a = joinName(cdName);
      alias.set(cdName, a);
      const on = fk.map((f, i) => {
        const l = colSql('source', f!.table, f!.column);
        const r = colSql(a, pk[i]!.table, pk[i]!.column);
        return l && r ? `${l} = ${r}` : null;
      });
      if (on.some((x) => !x)) {
        issues.push(`${cdName} joins on a computed column. Write the join by hand.`);
        continue;
      }
      joins.push({ name: a, source: t, on: on.join(' AND ') });
    } else if (type !== 'Degenerate') {
      issues.push(`${cdName} is a ${type.toLowerCase()} dimension, so it is left out.`);
      continue;
    }
    for (const at of attrs) {
      const nameCol = bindingOf(child(at, 'NameColumn'));
      const keys = keyColumns(at);
      if (at === key && !nameCol) continue; // a surrogate key
      const b = nameCol ?? (keys.length === 1 ? keys[0] : null);
      const n = unique(
        (roleCount.get(txt(dim, 'ID')!) ?? 0) > 1 ? `${cdName} ${txt(at, 'Name')}` : (txt(at, 'Name') ?? 'Attribute')
      );
      const source = `${cdName}.${txt(at, 'Name')}: ${b ? `${b.table}.${b.column}` : 'composite key'}`;
      const sql = b && b.table === dimTable ? colSql(a, b.table, b.column) : null;
      if (!sql) {
        fields.push({
          name: n,
          kind: 'dimension',
          source,
          status: 'manual',
          note: !b
            ? 'A composite key with no name column.'
            : b.table !== dimTable
              ? 'On a snowflake table: a nested join.'
              : 'A computed column.',
        });
        continue;
      }
      view.dimensions.push({ name: n, expr: sql });
      explanations.dimensions[n] = { explanation: note('converted', source) };
      fields.push({ name: n, kind: 'dimension', source, status: 'converted', note: '' });
    }
  }
  if (joins.length) view.joins = joins;

  // Base measures, then calculated members in passes, so each comes after the measures it uses.
  const done = new Set<string>();
  const push = (name: string, expr: string, status: FieldStatus, source: string, additive: boolean) => {
    view.measures.push({ name, expr });
    done.add(name.toLowerCase());
    explanations.measures[name] = {
      additivity: additive ? 'additive' : expr.includes('/') ? 'ratio' : 'non_additive',
      explanation: note(status, source),
    };
    fields.push({
      name,
      kind: 'measure',
      source,
      status,
      note: status === 'review' ? 'Translated by the AI. Check it with a test.' : '',
    });
  };
  const names = new Map<string, string>();
  for (const m of measureNodes) {
    const name = txt(m, 'Name') ?? txt(m, 'ID') ?? 'Measure';
    names.set(name.toLowerCase(), name);
    const agg = (txt(m, 'AggregateFunction') ?? 'Sum').toLowerCase();
    const b = bindingOf(child(m, 'Source'));
    const source = `${txt(mg, 'Name')}.${name}: ${txt(m, 'AggregateFunction') ?? 'Sum'}(${b ? `${b.table}.${b.column ?? 'row'}` : ''})`;
    const col =
      b && b.table === factId ? (b.column ? colSql('', b.table, b.column) : agg === 'count' ? '1' : null) : null;
    if (child(m, 'MeasureExpression') || !col || !AGG[agg]) {
      fields.push({
        name,
        kind: 'measure',
        source,
        status: 'manual',
        note: child(m, 'MeasureExpression')
          ? 'A measure expression.'
          : !AGG[agg]
            ? `A semi-additive measure (${txt(m, 'AggregateFunction')}).`
            : 'A computed column or another table.',
      });
      continue;
    }
    push(name, AGG[agg](col), 'converted', source, agg === 'sum' || agg === 'count');
  }
  for (const c of calcs) names.set(c.name.toLowerCase(), c.name);
  const measure = (n: string) => (done.has(n.toLowerCase()) ? `MEASURE(${quote(names.get(n.toLowerCase())!)})` : null);
  const left = new Map(calcs.map((c) => [c.name, c]));
  for (let pass = 0; pass < 4 && left.size; pass++)
    for (const c of [...left.values()]) {
      const sql = translateMdx(c.expr, measure);
      if (sql) {
        left.delete(c.name);
        push(c.name, sql, 'converted', `${c.name} = ${c.expr}`, false);
      }
    }
  for (const c of left.values()) {
    if (ai.has(c.name)) {
      push(c.name, ai.get(c.name)!, 'review', `${c.name} = ${c.expr}`, false);
      continue;
    }
    todo.push({ name: c.name, dax: c.expr });
    fields.push({
      name: c.name,
      kind: 'measure',
      source: `${c.name} = ${c.expr}`,
      status: 'manual',
      note: 'An MDX expression with no rule, such as a tuple, a set or a time function.',
    });
  }

  const result = finish(
    'ssas',
    'SSAS Multidimensional',
    fileName,
    view,
    fields,
    [factTable, ...joins.map((j) => j.source)],
    issues,
    explanations
  );
  const columns = [...(tables.get(factId)?.columns ?? new Map())].flatMap(([id]) => {
    const sql = colSql('', factId, id as string);
    return sql ? [{ table: factId, column: id as string, sql }] : [];
  });
  return { ...result, todo, catalog: { columns, measures: [...done].map((k) => names.get(k)!) } };
}
