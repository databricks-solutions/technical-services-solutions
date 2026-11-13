import { parse } from 'yaml';
import type { Explanations } from '../../shared/designer';
import type { FieldStatus, LegacyField } from '../../shared/legacy';
import { finish, human, IDENT, namer, noteOf, quote } from './common';
import type { LegacyResult } from './common';
import type { MetricView } from '../../shared/metricView';

/**
 * dbt MetricFlow to a metric view, by rules only. The input is `semantic_models` and `metrics` YAML, or the
 * `semantic_manifest.json` that `dbt parse` writes. One semantic model is the fact (it holds the most measures that
 * the metrics use); the others join to it when its foreign entity is their primary entity. Each metric becomes a
 * measure. Each field keeps its dbt definition and a status, so a person checks what the rules could not prove.
 */

interface DbtEntity {
  name: string;
  type?: string;
  expr?: string;
}
interface DbtDimension {
  name: string;
  type?: string;
  expr?: string;
  label?: string;
  description?: string;
  type_params?: { time_granularity?: string };
}
interface DbtMeasure {
  name: string;
  agg?: string;
  expr?: string | number | boolean;
  description?: string;
  agg_params?: { percentile?: number; use_discrete_percentile?: boolean };
}
interface DbtSemanticModel {
  name: string;
  model?: string;
  node_relation?: { relation_name?: string; database?: string; schema_name?: string; alias?: string };
  description?: string;
  entities?: DbtEntity[];
  dimensions?: DbtDimension[];
  measures?: DbtMeasure[];
}
type MeasureRef = string | { name: string; filter?: unknown; alias?: string };
interface DbtMetric {
  name: string;
  type?: string;
  label?: string;
  description?: string;
  filter?: unknown;
  type_params?: {
    measure?: MeasureRef;
    numerator?: MeasureRef;
    denominator?: MeasureRef;
    expr?: string;
    metrics?: (string | { name: string; alias?: string; offset_window?: unknown; offset_to_grain?: unknown })[];
    window?: unknown;
    grain_to_date?: unknown;
  };
}

const MAX_ITEMS = 500;
const asArray = <T>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]).slice(0, MAX_ITEMS) : []);
const refName = (r: MeasureRef | undefined) => (typeof r === 'string' ? r : r?.name);
const filterText = (f: unknown): string | null =>
  typeof f === 'string' ? f : Array.isArray(f) ? f.filter((x) => typeof x === 'string').join(' AND ') || null : null;

/** Reads the file. Throws a message for the user when it is neither format. */
export function readDbt(fileName: string, content: string): { models: DbtSemanticModel[]; metrics: DbtMetric[] } {
  let doc: unknown;
  try {
    doc = /\.json$/i.test(fileName) ? JSON.parse(content) : parse(content, { maxAliasCount: 100 });
  } catch (err) {
    throw new Error(`The file does not parse: ${(err as Error).message.split('\n')[0]}`);
  }
  const d = (doc ?? {}) as Record<string, unknown>;
  const models = asArray<DbtSemanticModel>(d.semantic_models).filter((m) => typeof m?.name === 'string');
  const metrics = asArray<DbtMetric>(d.metrics).filter((m) => typeof m?.name === 'string');
  if (!models.length)
    throw new Error('The file has no semantic_models. Use dbt MetricFlow YAML or semantic_manifest.json.');
  return { models, metrics };
}

/** The Unity Catalog table of a semantic model: the manifest relation, or ref('x') in the given catalog.schema. */
function tableOf(m: DbtSemanticModel, schema: string | undefined): string | null {
  const r = m.node_relation;
  if (r?.database && r.schema_name && r.alias) return `${r.database}.${r.schema_name}.${r.alias}`;
  if (r?.relation_name) return r.relation_name.replace(/[`"]/g, '');
  const ref = /ref\(\s*['"]([^'"]+)['"]\s*\)/.exec(m.model ?? '')?.[1];
  return ref && schema ? `${schema}.${ref}` : null;
}

const AGG: Record<string, (e: string, m: DbtMeasure) => string> = {
  sum: (e) => `SUM(${e})`,
  count: (e) => `COUNT(${e})`,
  count_distinct: (e) => `COUNT(DISTINCT ${e})`,
  average: (e) => `AVG(${e})`,
  min: (e) => `MIN(${e})`,
  max: (e) => `MAX(${e})`,
  sum_boolean: (e) => `SUM(CAST(${e} AS INT))`,
  median: (e) => `MEDIAN(${e})`,
  percentile: (e, m) =>
    `${m.agg_params?.use_discrete_percentile ? 'PERCENTILE_DISC' : 'PERCENTILE_CONT'}(${m.agg_params?.percentile ?? 0.5}) WITHIN GROUP (ORDER BY ${e})`,
};
const ADDITIVE = new Set(['sum', 'count', 'sum_boolean']);

export function convertDbt(fileName: string, content: string, schema?: string): LegacyResult {
  const { models, metrics } = readDbt(fileName, content);
  const issues: string[] = [];
  const fields: LegacyField[] = [];
  const measureOwner = new Map<string, { model: DbtSemanticModel; measure: DbtMeasure }>();
  for (const model of models)
    for (const ms of asArray<DbtMeasure>(model.measures)) measureOwner.set(ms.name, { model, measure: ms });

  // The fact owns the most measures that the metrics use (all measures when there are no metrics).
  const used = (m: DbtMetric) =>
    [m.type_params?.measure, m.type_params?.numerator, m.type_params?.denominator]
      .map(refName)
      .filter(Boolean) as string[];
  const score = new Map<string, number>();
  const counted = metrics.length ? metrics.flatMap(used) : [...measureOwner.keys()];
  for (const n of counted) {
    const owner = measureOwner.get(n)?.model.name;
    if (owner) score.set(owner, (score.get(owner) ?? 0) + 1);
  }
  const fact = [...models].sort((a, b) => (score.get(b.name) ?? 0) - (score.get(a.name) ?? 0))[0];
  const factTable = tableOf(fact, schema);
  if (!factTable)
    return {
      preview: {
        format: 'dbt',
        yaml: null,
        fields: [],
        sources: [],
        issues: [`${fact.name} has no table. Type the catalog.schema of the dbt models.`],
      },
      view: null,
      explanations: { summary: '', measures: {}, dimensions: {} },
    };

  // Joins: a foreign entity of the fact that is the primary (or unique) entity of another semantic model.
  const keyOf = (e: DbtEntity) => e.expr ?? e.name;
  const joined = new Map<string, { model: DbtSemanticModel; table: string }>();
  const joins: NonNullable<MetricView['joins']> = [];
  for (const fk of asArray<DbtEntity>(fact.entities).filter((e) => e.type === 'foreign')) {
    for (const other of models) {
      if (other === fact || joined.has(other.name)) continue;
      const pk = asArray<DbtEntity>(other.entities).find(
        (e) => e.name === fk.name && (e.type === 'primary' || e.type === 'unique' || e.type === 'natural')
      );
      const table = tableOf(other, schema);
      if (!pk || !table) continue;
      if (!IDENT.test(keyOf(fk)) || !IDENT.test(keyOf(pk))) {
        issues.push(`The join of ${other.name} uses a key expression. Add the join by hand.`);
        continue;
      }
      joined.set(other.name, { model: other, table });
      joins.push({ name: other.name, source: table, on: `source.${keyOf(fk)} = ${other.name}.${keyOf(pk)}` });
    }
  }
  for (const m of models)
    if (m !== fact && !joined.has(m.name))
      issues.push(`${m.name} does not join to ${fact.name} by an entity, so its fields are left out.`);

  // A column expression of a semantic model, as the metric view sees it. null when it cannot be placed safely.
  const place = (model: DbtSemanticModel, expr: string): { sql: string; status: FieldStatus } | null => {
    if (model === fact) return { sql: expr, status: 'converted' };
    if (!joined.has(model.name)) return null;
    if (IDENT.test(expr)) return { sql: `${model.name}.${expr}`, status: 'converted' };
    return null;
  };

  const view: MetricView = {
    version: '1.1',
    source: factTable,
    ...(fact.description ? { comment: fact.description } : {}),
    ...(joins.length ? { joins } : {}),
    dimensions: [],
    measures: [],
  };
  const explanations: Explanations = { summary: '', measures: {}, dimensions: {} };
  const unique = namer();
  const note = (status: FieldStatus, text: string) => noteOf('dbt', status, text);

  // Dimensions: each model in the view; for time dimensions the column as it is.
  const dimByRef = new Map<string, string>();
  for (const model of [fact, ...[...joined.values()].map((j) => j.model)]) {
    for (const d of asArray<DbtDimension>(model.dimensions)) {
      const expr = d.expr ?? d.name;
      const placed = place(model, expr);
      const source = `${model.name}.${d.name}: ${expr}${d.type_params?.time_granularity ? ` (${d.type}, ${d.type_params.time_granularity})` : ''}`;
      const name = unique(d.label ?? human(d.name));
      if (!placed) {
        fields.push({
          name,
          kind: 'dimension',
          source,
          status: 'manual',
          note: 'A complex expression on a joined model.',
        });
        continue;
      }
      view.dimensions.push({
        name,
        expr: placed.sql,
        ...(d.description ? { comment: d.description } : {}),
        synonyms: [d.name],
      });
      dimByRef.set(`${model.name}__${d.name}`.toLowerCase(), placed.sql);
      dimByRef.set(d.name.toLowerCase(), dimByRef.get(d.name.toLowerCase()) ?? placed.sql);
      explanations.dimensions[name] = { explanation: note(placed.status, source) };
      fields.push({ name, kind: 'dimension', source, status: placed.status, note: '' });
    }
  }

  /** dbt filters use Jinja: {{ Dimension('order__status') }}. Only dimensions of the view can be replaced. */
  const resolveFilter = (f: string | null): string | null | undefined => {
    if (!f) return undefined;
    const out = f.replace(/\{\{\s*Dimension\(\s*['"]([^'"]+)['"]\s*\)\s*\}\}/g, (all, ref: string) => {
      const key = ref.toLowerCase();
      return dimByRef.get(key) ?? dimByRef.get(key.split('__').pop()!) ?? all;
    });
    return out.includes('{{') ? null : out;
  };

  /** One aggregated dbt measure, with an optional filter, placed in the view. */
  const aggregate = (ref: MeasureRef | undefined, metricFilter: unknown) => {
    const n = refName(ref);
    const owner = n ? measureOwner.get(n) : undefined;
    if (!owner) return { error: `The measure ${n ?? '(none)'} is not in the file.` };
    const agg = owner.measure.agg ?? '';
    const make = AGG[agg];
    if (!make) return { error: `The aggregation ${agg || '(none)'} has no rule.` };
    const placed = place(owner.model, String(owner.measure.expr ?? owner.measure.name));
    if (!placed) return { error: `${owner.model.name} does not join, or its expression is complex.` };
    const filters = [filterText(typeof ref === 'object' ? ref.filter : undefined), filterText(metricFilter)].filter(
      Boolean
    );
    const where = filters.length ? resolveFilter(filters.join(' AND ')) : undefined;
    if (where === null) return { error: 'The filter uses Jinja that the rules cannot replace.' };
    let sql = make(placed.sql, owner.measure);
    if (where) sql = `${sql} FILTER (WHERE ${where})`;
    const status: FieldStatus = owner.model !== fact || agg === 'percentile' ? 'review' : placed.status;
    return { sql, status, agg };
  };

  const measureName = new Map<string, string>();
  const ordered = metrics.length
    ? // Simple metrics first, so ratio and derived metrics can refer to them.
      [...metrics].sort((a, b) => Number(a.type !== 'simple') - Number(b.type !== 'simple'))
    : [...measureOwner.values()].map(
        ({ measure }) =>
          ({
            name: measure.name,
            type: 'simple',
            description: measure.description,
            type_params: { measure: measure.name },
          }) as DbtMetric
      );
  for (const m of ordered) measureName.set(m.name, m.label ?? human(m.name));
  const ref = (n: string) => `MEASURE(${quote(measureName.get(n) ?? n)})`;
  const done = new Set<string>();

  for (const m of ordered) {
    const name = unique(m.label ?? human(m.name));
    measureName.set(m.name, name);
    const source = `${m.name} (${m.type ?? 'simple'}): ${JSON.stringify(m.type_params ?? {})}${m.filter ? ` filter ${JSON.stringify(m.filter)}` : ''}`;
    let sql: string | null = null;
    let status: FieldStatus = 'converted';
    let additivity: Explanations['measures'][string]['additivity'] = 'non_additive';
    let why = '';
    const p = m.type_params ?? {};
    if ((m.type ?? 'simple') === 'simple') {
      const r = aggregate(p.measure, m.filter);
      if ('error' in r) why = r.error!;
      else {
        sql = r.sql;
        status = r.status;
        additivity = ADDITIVE.has(r.agg) ? 'additive' : 'non_additive';
      }
    } else if (m.type === 'ratio') {
      const num = refName(p.numerator);
      const den = refName(p.denominator);
      if (!num || !den || !done.has(num) || !done.has(den) || m.filter)
        why = 'A ratio of metrics that are not converted, or with a filter.';
      else {
        sql = `${ref(num)} / NULLIF(${ref(den)}, 0)`;
        additivity = 'ratio';
      }
    } else if (m.type === 'derived') {
      const parts = asArray<
        string | { name: string; alias?: string; offset_window?: unknown; offset_to_grain?: unknown }
      >(p.metrics);
      const offsets = parts.some((x) => typeof x === 'object' && (x.offset_window || x.offset_to_grain));
      const alias = new Map(parts.map((x) => (typeof x === 'string' ? [x, x] : [x.alias ?? x.name, x.name])));
      if (offsets || !p.expr || m.filter)
        why = 'A derived metric with an offset or a filter: make it a window measure by hand.';
      else if ([...alias.values()].some((n) => !done.has(n))) why = 'It uses a metric that is not converted.';
      else {
        sql = p.expr.replace(/[A-Za-z_][A-Za-z0-9_]*/g, (w) => (alias.has(w) ? ref(alias.get(w)!) : w));
        status = 'review';
      }
    } else if (m.type === 'cumulative') {
      why = 'A cumulative metric: add it as a window measure on the time dimension.';
    } else why = `The ${m.type} metric type has no rule.`;

    if (!sql) {
      fields.push({ name, kind: 'measure', source, status: 'manual', note: why });
      continue;
    }
    done.add(m.name);
    view.measures.push({ name, expr: sql, ...(m.description ? { comment: m.description } : {}), synonyms: [m.name] });
    explanations.measures[name] = { additivity, explanation: note(status, source) };
    fields.push({ name, kind: 'measure', source, status, note: status === 'review' ? 'Check it with a test.' : '' });
  }

  return finish(
    'dbt',
    'dbt MetricFlow',
    fileName,
    view,
    fields,
    [factTable, ...[...joined.values()].map((j) => j.table)],
    issues,
    explanations
  );
}
