import type { Explanations } from '../../shared/designer';
import type { FieldStatus, LegacyField } from '../../shared/legacy';
import type { MetricView } from '../../shared/metricView';
import { finish, human, IDENT, namer, noteOf } from './common';
import type { LegacyResult } from './common';
import { translateDax } from './dax';
import { readZipEntry } from './zip';

/**
 * Power BI (.pbit) and SSAS Tabular (.bim) to a metric view. Both hold a TMSL model: tables with columns, measures
 * in DAX, relationships, and partitions that name the source. The fact is the table on the many side of the most
 * relationships; its relationships become joins. DAX measures convert by rules (dax.ts); the rest can go to the AI,
 * whose SQL is always marked to check.
 */

interface TmslColumn {
  name: string;
  dataType?: string;
  sourceColumn?: string;
  isHidden?: boolean;
  type?: string;
  expression?: string | string[];
  description?: string;
}
interface TmslMeasure {
  name: string;
  expression?: string | string[];
  description?: string;
  isHidden?: boolean;
}
interface TmslTable {
  name: string;
  description?: string;
  isHidden?: boolean;
  columns?: TmslColumn[];
  measures?: TmslMeasure[];
  partitions?: { source?: { type?: string; expression?: string | string[]; query?: string | string[] } }[];
}
interface TmslRelationship {
  fromTable: string;
  fromColumn: string;
  toTable: string;
  toColumn: string;
  isActive?: boolean;
}

const text = (v: string | string[] | undefined) => (Array.isArray(v) ? v.join('\n') : (v ?? ''));
const slug = (s: string) =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, '_')
    .replace(/^_+|_+$/g, '') || 't';
const MAX_ITEMS = 2000;
const list = <T>(v: T[] | undefined) => (Array.isArray(v) ? v.slice(0, MAX_ITEMS) : []);

/** The TMSL model of a .bim file (JSON) or of a .pbit template (DataModelSchema, UTF-16, in a zip). */
export function readTabular(fileName: string, content: string, base64: boolean) {
  let json: string;
  if (/\.pbit$/i.test(fileName)) {
    if (!base64) throw new Error('A .pbit file must be sent as binary.');
    const raw = readZipEntry(Buffer.from(content, 'base64'), (n) => n === 'DataModelSchema');
    if (!raw)
      throw new Error('The template has no DataModelSchema. Save it again in Power BI Desktop as a .pbit file.');
    json = raw[0] === 0xff && raw[1] === 0xfe ? raw.subarray(2).toString('utf16le') : raw.toString('utf16le');
    if (!json.trimStart().startsWith('{')) json = raw.toString('utf8');
  } else json = content;
  let doc: { model?: { tables?: TmslTable[]; relationships?: TmslRelationship[] } };
  try {
    doc = JSON.parse(json.replace(/^\uFEFF/, '')) as typeof doc;
  } catch (err) {
    throw new Error(`The model does not parse: ${(err as Error).message}`);
  }
  const tables = list(doc.model?.tables).filter((t) => typeof t?.name === 'string');
  if (!tables.length) throw new Error('The file has no model tables. Use a .bim file or a .pbit template.');
  return { tables, relationships: list(doc.model?.relationships).filter((r) => r.isActive !== false) };
}

/**
 * The Unity Catalog table of a TMSL table: from a Databricks connector in Power Query M (catalog, schema and table
 * names), else the default catalog.schema and the source item name, which a person checks.
 */
function tableOf(t: TmslTable, schema: string | undefined): { table: string; sure: boolean } | null {
  const src = t.partitions?.[0]?.source;
  const m = text(src?.expression);
  const kinds = (kind: string) => new RegExp(`\\{\\[Name="([^"]+)",Kind="${kind}"\\]\\}`).exec(m)?.[1];
  const [c, s, n] = [kinds('Database'), kinds('Schema'), kinds('Table') ?? kinds('View')];
  if (c && s && n) return { table: `${c}.${s}.${n}`, sure: true };
  if (src?.type === 'query' || src?.type === 'calculated') return null;
  const item = /Item="([^"]+)"/.exec(m)?.[1];
  return schema ? { table: `${schema}.${slug(item ?? t.name)}`, sure: false } : null;
}

export interface TabularResult extends LegacyResult {
  /** Measures that the rules could not translate, for the AI. */
  todo: { name: string; dax: string }[];
  /** What the AI can use: the columns in the view and the converted measures. */
  catalog: { columns: { table: string; column: string; sql: string }[]; measures: string[] };
}

export function convertTabular(
  fileName: string,
  content: string,
  schema: string | undefined,
  base64: boolean,
  /** SQL from the AI for measures in todo, by measure name. Always marked to check. */
  ai: Map<string, string> = new Map()
): TabularResult {
  const { tables, relationships } = readTabular(fileName, content, base64);
  const issues: string[] = [];
  const fields: LegacyField[] = [];
  const explanations: Explanations = { summary: '', measures: {}, dimensions: {} };
  const todo: TabularResult['todo'] = [];

  // The fact: on the many side of the most relationships; else the table with the most columns.
  const many = new Map<string, number>();
  for (const r of relationships) many.set(r.fromTable, (many.get(r.fromTable) ?? 0) + 1);
  const withColumns = tables.filter((t) => list(t.columns).some((c) => c.type !== 'rowNumber'));
  const fact = [...withColumns].sort(
    (a, b) => (many.get(b.name) ?? 0) - (many.get(a.name) ?? 0) || list(b.columns).length - list(a.columns).length
  )[0];
  const empty = (why: string): TabularResult => ({
    preview: { format: 'tabular', yaml: null, fields: [], sources: [], issues: [why] },
    view: null,
    explanations,
    todo,
    catalog: { columns: [], measures: [] },
  });
  if (!fact) return empty('The model has no table with columns.');
  const factSource = tableOf(fact, schema);
  if (!factSource)
    return empty(`${fact.name} has no Databricks table in its source. Type the catalog.schema of the tables.`);
  if (!factSource.sure) issues.push(`${fact.name} was mapped by name to ${factSource.table}. Check it.`);

  // Joins: relationships from the fact to the one side. One level; other relationships are left out.
  const alias = new Map<string, string>([[fact.name, '']]);
  const joins: NonNullable<MetricView['joins']> = [];
  const byName = new Map(tables.map((t) => [t.name, t]));
  const columnSql = (table: string, column: string) => {
    const t = byName.get(table);
    const a = alias.get(table);
    const col = list(t?.columns).find((c) => c.name === column);
    if (a === undefined || !col || col.type === 'calculated') return null;
    const src = col.sourceColumn ?? col.name;
    const ref = IDENT.test(src) ? src : `\`${src.replace(/`/g, '``')}\``;
    return a ? `${a}.${ref}` : ref;
  };
  for (const r of relationships) {
    if (r.fromTable !== fact.name || alias.has(r.toTable)) continue;
    const to = byName.get(r.toTable);
    const src = to && tableOf(to, schema);
    if (!to || !src) {
      issues.push(`${r.toTable} has no Databricks table in its source, so it is left out.`);
      continue;
    }
    if (!src.sure) issues.push(`${r.toTable} was mapped by name to ${src.table}. Check it.`);
    const a = slug(r.toTable);
    alias.set(r.toTable, a);
    const fk = columnSql(fact.name, r.fromColumn);
    const pk = columnSql(r.toTable, r.toColumn);
    if (!fk || !pk) {
      issues.push(`The relationship to ${r.toTable} uses a calculated column. Write the join by hand.`);
      alias.delete(r.toTable);
      continue;
    }
    joins.push({ name: a, source: src.table, on: `source.${fk} = ${pk}` });
  }
  for (const r of relationships)
    if (r.fromTable !== fact.name && alias.has(r.fromTable) && !alias.has(r.toTable))
      issues.push(`${r.fromTable} -> ${r.toTable} is a second-level relationship. Add it as a nested join by hand.`);

  const view: MetricView = {
    version: '1.1',
    source: factSource.table,
    ...(fact.description ? { comment: fact.description } : {}),
    ...(joins.length ? { joins } : {}),
    dimensions: [],
    measures: [],
  };
  const unique = namer();
  const note = (status: FieldStatus, t: string) => noteOf('Power BI / Tabular', status, t);
  const measures = tables.flatMap((t) => list(t.measures).map((m) => ({ table: t.name, m })));
  // Measure names stay as in the model, because other measures refer to them; a column with the same name is renamed.
  for (const { m } of measures) unique(m.name);

  // Dimensions: visible text, date and boolean columns, and numeric columns that do not sum by default.
  for (const table of alias.keys())
    for (const c of list(byName.get(table)?.columns)) {
      if (c.isHidden || c.type === 'rowNumber') continue;
      const source = `${table}[${c.name}]${c.type === 'calculated' ? ` = ${text(c.expression)}` : ''} (${c.dataType ?? 'string'})`;
      const name = unique(c.name.includes('_') ? human(c.name) : c.name);
      if (c.type === 'calculated') {
        fields.push({ name, kind: 'dimension', source, status: 'manual', note: 'A calculated column in DAX.' });
        continue;
      }
      if (/^(int64|decimal|double)$/i.test(c.dataType ?? '') && !/key|id$/i.test(c.name)) continue;
      const expr = columnSql(table, c.name)!;
      view.dimensions.push({ name, expr, ...(c.description ? { comment: c.description } : {}) });
      explanations.dimensions[name] = { explanation: note('converted', source) };
      fields.push({ name, kind: 'dimension', source, status: 'converted', note: '' });
    }

  // Measures in the order of the model, with a second pass for measures that refer to later ones.
  const done = new Set<string>();
  const sqlOf = new Map<string, { sql: string; status: FieldStatus }>();
  const ctx = {
    column: columnSql,
    measure: (n: string) => done.has(n),
    table: (n: string) => alias.has(n),
  };
  for (let pass = 0; pass < 3; pass++)
    for (const { m } of measures) {
      if (done.has(m.name)) continue;
      const sql = translateDax(text(m.expression), ctx);
      if (sql) {
        done.add(m.name);
        sqlOf.set(m.name, { sql, status: 'converted' });
      }
    }
  for (const { m } of measures)
    if (!done.has(m.name) && ai.has(m.name)) {
      done.add(m.name);
      sqlOf.set(m.name, { sql: ai.get(m.name)!, status: 'review' });
    }
  for (const { table, m } of measures) {
    const dax = text(m.expression);
    const source = `${table}[${m.name}] = ${dax}`;
    const r = sqlOf.get(m.name);
    if (!r) {
      todo.push({ name: m.name, dax });
      fields.push({ name: m.name, kind: 'measure', source, status: 'manual', note: 'DAX with no rule.' });
      continue;
    }
    // Measure names stay as in the model: other measures refer to them with MEASURE(`name`).
    view.measures.push({ name: m.name, expr: r.sql, ...(m.description ? { comment: m.description } : {}) });
    explanations.measures[m.name] = {
      additivity:
        /^(SUM|COUNT)\(/.test(r.sql) && !r.sql.includes('DISTINCT')
          ? 'additive'
          : r.sql.includes('/')
            ? 'ratio'
            : 'non_additive',
      explanation: note(r.status, source),
    };
    fields.push({
      name: m.name,
      kind: 'measure',
      source,
      status: r.status,
      note: r.status === 'review' ? 'Translated by the AI. Check it with a test.' : '',
    });
  }
  const result = finish(
    'tabular',
    'Power BI / Tabular',
    fileName,
    view,
    fields,
    [factSource.table, ...joins.map((j) => j.source)],
    issues,
    explanations
  );
  const columns = [...alias.keys()].flatMap((table) =>
    list(byName.get(table)?.columns).flatMap((c) => {
      const sql = columnSql(table, c.name);
      return sql ? [{ table, column: c.name, sql }] : [];
    })
  );
  return { ...result, todo, catalog: { columns, measures: [...done] } };
}
