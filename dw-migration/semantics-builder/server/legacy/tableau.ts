import type { Explanations } from '../../shared/designer';
import type { FieldStatus, LegacyField } from '../../shared/legacy';
import type { MetricView } from '../../shared/metricView';
import { finish, human, IDENT, namer, noteOf, quote } from './common';
import type { AiResult } from './common';
import { aggregates, translateTableau } from './tableauCalc';
import { child, findAll, parseXml } from './xml';
import type { XmlNode } from './xml';
import { readZipEntry } from './zip';

/**
 * Tableau (.twb, .tds, and the zipped .twbx, .tdsx) to a metric view. The first data source with tables is read:
 * its tables (relations), its joins (legacy join clauses, or the relationships of the object model), its columns
 * (metadata records), and its calculated fields. Numeric columns become measures with their default aggregation.
 * Calculations convert by rules (tableauCalc.ts); measures with no rule can go to the AI, always marked to check.
 */

const unbracket = (s: string) => s.replace(/^\[|\]$/g, '');
const slug = (s: string) =>
  s
    .toLowerCase()
    .replace(/[^a-z0-9_]+/g, '_')
    .replace(/^_+|_+$/g, '') || 't';
const AGG: Record<string, (e: string) => string> = {
  Sum: (e) => `SUM(${e})`,
  Avg: (e) => `AVG(${e})`,
  Count: (e) => `COUNT(${e})`,
  CountD: (e) => `COUNT(DISTINCT ${e})`,
  Min: (e) => `MIN(${e})`,
  Max: (e) => `MAX(${e})`,
  Median: (e) => `MEDIAN(${e})`,
};
const NUMERIC = /^(integer|real|decimal|double)$/i;

/** The workbook or data source XML, from the file or from the zip. */
export function readTableau(fileName: string, content: string, base64: boolean): XmlNode {
  let xml = content;
  if (/\.(twbx|tdsx)$/i.test(fileName)) {
    if (!base64) throw new Error('A packaged Tableau file must be sent as binary.');
    const raw = readZipEntry(Buffer.from(content, 'base64'), (n) => /\.(twb|tds)$/i.test(n) && !n.includes('/'));
    if (!raw) throw new Error('The package has no .twb or .tds file at its top level.');
    xml = raw.toString('utf8');
  }
  return parseXml(xml.replace(/^\uFEFF/, ''));
}

export function convertTableau(
  fileName: string,
  content: string,
  schema: string | undefined,
  base64: boolean,
  ai: Map<string, string> = new Map()
): AiResult {
  const root = readTableau(fileName, content, base64);
  const issues: string[] = [];
  const fields: LegacyField[] = [];
  const explanations: Explanations = { summary: '', measures: {}, dimensions: {} };
  const todo: AiResult['todo'] = [];
  const empty = (why: string): AiResult => ({
    preview: { format: 'tableau', yaml: null, fields: [], sources: [], issues: [why] },
    view: null,
    explanations,
    todo,
    catalog: { columns: [], measures: [] },
  });

  const ds = findAll(root, 'datasource').find(
    (d) => d.attrs.name !== 'Parameters' && findAll(d, 'relation').some((r) => r.attrs.type === 'table')
  );
  if (!ds) return empty('The file has no data source with tables. Custom SQL and extracts only are not converted.');

  // Tables: the relations of type table. The first one is the fact (the left table of the joins).
  const named = new Map(
    findAll(ds, 'named-connection').map((n) => [n.attrs.name, child(n, 'connection')?.attrs ?? {}])
  );
  const relations = findAll(ds, 'relation').filter((r) => r.attrs.type === 'table' && r.attrs.name);
  const tables = new Map<string, { table: string; sure: boolean }>();
  for (const r of relations) {
    if (tables.has(r.attrs.name)) continue;
    const parts = (r.attrs.table ?? '').split('].[').map(unbracket);
    const conn = named.get(r.attrs.connection) ?? child(ds, 'connection')?.attrs ?? {};
    const catalog = conn.catalog || conn.dbname || schema?.split('.')[0];
    const full =
      parts.length === 3
        ? parts.join('.')
        : parts.length === 2 && catalog
          ? `${catalog}.${parts.join('.')}`
          : parts.length === 1 && schema
            ? `${schema}.${parts[0]}`
            : null;
    if (full) tables.set(r.attrs.name, { table: full, sure: parts.length === 3 || !!(conn.catalog || conn.dbname) });
  }
  const custom = findAll(ds, 'relation').filter((r) => r.attrs.type === 'text');
  if (custom.length)
    issues.push(`${custom.length} custom SQL relation(s) are left out. Make them tables or views first.`);
  const factName = relations[0]?.attrs.name;
  const fact = factName ? tables.get(factName) : undefined;
  if (!fact) return empty('The fact table has a short name. Type the catalog.schema of the tables.');
  if (!fact.sure) issues.push(`${factName} was mapped to ${fact.table}. Check it.`);

  // Columns: metadata records give the table (parent) and the source name (remote) of each local name.
  const records = new Map<string, { table: string; remote: string; type: string; agg: string }>();
  for (const m of findAll(ds, 'metadata-record').filter((x) => x.attrs.class === 'column')) {
    const local = child(m, 'local-name')?.text.trim();
    const remote = child(m, 'remote-name')?.text.trim();
    if (!local || !remote) continue;
    records.set(unbracket(local), {
      table: unbracket(child(m, 'parent-name')?.text.trim() ?? `[${factName}]`),
      remote,
      type: child(m, 'local-type')?.text.trim() ?? 'string',
      agg: child(m, 'aggregation')?.text.trim() ?? 'Sum',
    });
  }

  // Joins: legacy join clauses ([a].[x] = [b].[y]) or object model relationships ([x] = [y (b)]).
  const alias = new Map<string, string>([[factName, '']]);
  const joins: NonNullable<MetricView['joins']> = [];
  const colSql = (table: string, remote: string) => {
    const a = alias.get(table);
    if (a === undefined) return null;
    const ref = IDENT.test(remote) ? remote : quote(remote);
    return a ? `${a}.${ref}` : ref;
  };
  const pairs: [{ table: string; remote: string }, { table: string; remote: string }][] = [];
  for (const clause of findAll(ds, 'clause').filter((c) => c.attrs.type === 'join')) {
    const ops = findAll(clause, 'expression')
      .map((e) => e.attrs.op ?? '')
      .filter((op) => op.startsWith('['));
    const sides = ops.map((op) => op.split('].[').map(unbracket));
    if (sides.length === 2 && sides.every((s) => s.length === 2))
      pairs.push([
        { table: sides[0][0], remote: sides[0][1] },
        { table: sides[1][0], remote: sides[1][1] },
      ]);
  }
  for (const rel of findAll(ds, 'relationship')) {
    const ops = findAll(rel, 'expression')
      .map((e) => e.attrs.op ?? '')
      .filter((op) => op.startsWith('['));
    const recs = ops.map((op) => records.get(unbracket(op)));
    if (recs.length === 2 && recs[0] && recs[1])
      pairs.push([
        { table: recs[0].table, remote: recs[0].remote },
        { table: recs[1].table, remote: recs[1].remote },
      ]);
  }
  for (const [l, r] of pairs) {
    const [f, o] = l.table === factName ? [l, r] : r.table === factName ? [r, l] : [null, null];
    if (!f || !o) {
      issues.push(`The join of ${l.table} and ${r.table} does not touch the fact. Add it as a nested join by hand.`);
      continue;
    }
    const t = tables.get(o.table);
    if (!t || alias.has(o.table)) continue;
    if (!t.sure) issues.push(`${o.table} was mapped to ${t.table}. Check it.`);
    alias.set(o.table, slug(o.table));
    joins.push({
      name: slug(o.table),
      source: t.table,
      on: `source.${colSql(factName, f.remote)} = ${colSql(o.table, o.remote)}`,
    });
  }
  for (const name of tables.keys())
    if (!alias.has(name)) issues.push(`${name} does not join to ${factName}, so its fields are left out.`);

  const view: MetricView = {
    version: '1.1',
    source: fact.table,
    ...(joins.length ? { joins } : {}),
    dimensions: [],
    measures: [],
  };
  const unique = namer();
  const note = (status: FieldStatus, t: string) => noteOf('Tableau', status, t);

  // The column elements: captions, roles, hidden flags and calculations, by local name.
  const columns = new Map(
    ds.children.filter((c) => c.tag === 'column' && c.attrs.name).map((c) => [unbracket(c.attrs.name), c])
  );
  const captionOf = (local: string) => columns.get(local)?.attrs.caption ?? human(records.get(local)?.remote ?? local);
  const hidden = (local: string) => columns.get(local)?.attrs.hidden === 'true';

  for (const [local, r] of records) {
    if (hidden(local) || !alias.has(r.table)) continue;
    const sql = colSql(r.table, r.remote)!;
    const role = columns.get(local)?.attrs.role ?? (NUMERIC.test(r.type) ? 'measure' : 'dimension');
    const isKey = /(key|_id|id)$/i.test(r.remote);
    const source = `${r.table}.${r.remote} (${r.type}, ${role === 'measure' ? r.agg : 'dimension'})`;
    if (role === 'measure' && !isKey && AGG[r.agg]) {
      const name = unique(captionOf(local));
      view.measures.push({ name, expr: AGG[r.agg](sql), synonyms: [r.remote] });
      explanations.measures[name] = {
        additivity: r.agg === 'Sum' || r.agg === 'Count' ? 'additive' : 'non_additive',
        explanation: note('converted', source),
      };
      fields.push({ name, kind: 'measure', source, status: 'converted', note: '' });
    } else if (role !== 'measure' && !isKey) {
      const name = unique(captionOf(local));
      view.dimensions.push({ name, expr: sql, synonyms: [r.remote] });
      explanations.dimensions[name] = { explanation: note('converted', source) };
      fields.push({ name, kind: 'dimension', source, status: 'converted', note: '' });
    }
  }

  // Calculated fields, in passes, so a calculation can use one that comes later in the file.
  const calcs = [...columns.entries()].filter(([, c]) => child(c, 'calculation')?.attrs.formula !== undefined);
  const byRef = new Map<string, string>();
  for (const [local, c] of calcs) {
    byRef.set(local.toLowerCase(), local);
    if (c.attrs.caption) byRef.set(c.attrs.caption.toLowerCase(), local);
  }
  const sqlOf = new Map<string, { sql: string; status: FieldStatus }>();
  const names = new Map<string, string>();
  const field = (ref: string): string | null => {
    // A reference names a column by its local name, its source name or its caption.
    const byCaption = [...columns.entries()].find(
      ([l, c]) => records.has(l) && c.attrs.caption?.toLowerCase() === ref.toLowerCase()
    )?.[0];
    const rec =
      records.get(ref) ??
      (byCaption ? records.get(byCaption) : undefined) ??
      [...records.values()].find((r) => r.remote === ref);
    if (rec) return colSql(rec.table, rec.remote);
    const local = byRef.get(ref.toLowerCase());
    if (!local) return null;
    const done = sqlOf.get(local);
    if (!done) return null;
    const role = columns.get(local)?.attrs.role;
    return role === 'measure' ? `MEASURE(${quote(names.get(local)!)})` : `(${done.sql})`;
  };
  for (const [local, c] of calcs) names.set(local, unique(c.attrs.caption ?? human(local)));
  for (let pass = 0; pass < 4; pass++)
    for (const [local, c] of calcs) {
      if (sqlOf.has(local)) continue;
      const sql = translateTableau(child(c, 'calculation')!.attrs.formula, { field });
      if (sql) sqlOf.set(local, { sql, status: 'converted' });
    }
  for (const [local, c] of calcs)
    if (!sqlOf.has(local) && c.attrs.role === 'measure' && ai.has(names.get(local)!))
      sqlOf.set(local, { sql: ai.get(names.get(local)!)!, status: 'review' });

  for (const [local, c] of calcs) {
    const formula = child(c, 'calculation')!.attrs.formula;
    const name = names.get(local)!;
    const role = c.attrs.role === 'measure' ? 'measure' : 'dimension';
    const source = `${c.attrs.caption ?? local} (calculation, ${role}): ${formula}`;
    const r = sqlOf.get(local);
    if (!r || hidden(local)) {
      if (!r) {
        if (role === 'measure') todo.push({ name, dax: formula });
        fields.push({
          name,
          kind: role,
          source,
          status: 'manual',
          note: /\{/.test(formula) ? 'A LOD expression.' : 'A calculation with no rule.',
        });
      }
      continue;
    }
    if (role === 'dimension') {
      if (aggregates(r.sql)) {
        fields.push({ name, kind: 'dimension', source, status: 'manual', note: 'An aggregate in a dimension.' });
        continue;
      }
      view.dimensions.push({ name, expr: r.sql });
      explanations.dimensions[name] = { explanation: note(r.status, source) };
      fields.push({ name, kind: 'dimension', source, status: r.status, note: '' });
      continue;
    }
    // A row-level measure calculation is summed, as Tableau does by default.
    const expr = aggregates(r.sql) ? r.sql : `SUM(${r.sql})`;
    const status: FieldStatus = aggregates(r.sql) ? r.status : 'review';
    view.measures.push({ name, expr });
    explanations.measures[name] = {
      additivity: expr.includes('/') ? 'ratio' : 'non_additive',
      explanation: note(status, source),
    };
    fields.push({
      name,
      kind: 'measure',
      source,
      status,
      note:
        r.status === 'review'
          ? 'Translated by the AI. Check it with a test.'
          : status === 'review'
            ? 'A row-level calculation, summed.'
            : '',
    });
  }

  const catalogColumns = [...records.values()].flatMap((r) => {
    const sql = colSql(r.table, r.remote);
    return sql ? [{ table: r.table, column: r.remote, sql }] : [];
  });
  const result = finish(
    'tableau',
    'Tableau',
    fileName,
    view,
    fields,
    [fact.table, ...joins.map((j) => j.source)],
    issues,
    explanations
  );
  return {
    ...result,
    todo,
    catalog: { columns: catalogColumns, measures: view.measures.map((m) => m.name) },
  };
}
