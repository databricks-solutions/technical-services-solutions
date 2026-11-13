import { z } from 'zod';
import { isMap, isScalar, LineCounter, parseDocument, stringify } from 'yaml';

const text = z.string().trim().min(1);
const label = text.max(255);

const decimalPlaces = z.strictObject({
  type: z.enum(['max', 'exact', 'all']),
  places: z.number().int().min(0).max(20).optional(),
});
const numeric = {
  decimal_places: decimalPlaces.optional(),
  hide_group_separator: z.boolean().optional(),
};
const abbreviation = z.enum(['none', 'compact', 'scientific']).optional();
const dateFormat = z.enum([
  'year_month_day',
  'locale_short_month',
  'locale_long_month',
  'locale_number_month',
  'year_week',
]);

export const formatSchema = z.discriminatedUnion('type', [
  z.strictObject({ type: z.literal('number'), ...numeric, abbreviation }),
  z.strictObject({
    type: z.literal('currency'),
    currency_code: z.string().regex(/^[A-Z]{3}$/),
    ...numeric,
    abbreviation,
  }),
  z.strictObject({ type: z.literal('percentage'), ...numeric }),
  z.strictObject({ type: z.literal('byte'), ...numeric }),
  z.strictObject({ type: z.literal('date'), date_format: dateFormat, leading_zeros: z.boolean().optional() }),
  z
    .strictObject({
      type: z.literal('date_time'),
      date_format: z.union([dateFormat, z.literal('no_date')]).optional(),
      time_format: z.enum(['no_time', 'locale_hour_minute', 'locale_hour_minute_second']).optional(),
      leading_zeros: z.boolean().optional(),
    })
    .refine((f) => (f.date_format ?? 'no_date') !== 'no_date' || (f.time_format ?? 'no_time') !== 'no_time', {
      message: 'date_time needs a date_format or a time_format',
    }),
]);

const field = {
  name: label,
  expr: text,
  comment: text.optional(),
  synonyms: z.array(label).max(10).optional(),
  display_name: label.optional(),
  format: formatSchema.optional(),
};

const windowSpec = z.strictObject({
  order: text,
  range: z
    .string()
    .trim()
    .regex(/^(current|cumulative|all|(trailing|leading) \d+( [a-z]+)?( (inclusive|exclusive))?)$/i),
  semiadditive: z.enum(['first', 'last']).optional(),
  offset: z.union([z.number().int(), z.string().regex(/^-?\d+( [a-z]+)?$/i)]).optional(),
});

export interface Join {
  name: string;
  source: string;
  on?: string;
  using?: string[];
  cardinality?: 'many_to_one' | 'one_to_many';
  rely?: { at_most_one_match?: boolean };
  joins?: Join[];
}

const join: z.ZodType<Join> = z.lazy(() =>
  z
    .strictObject({
      name: text,
      source: text,
      on: text.optional(),
      using: z.array(text).min(1).optional(),
      cardinality: z.enum(['many_to_one', 'one_to_many']).optional(),
      rely: z.strictObject({ at_most_one_match: z.boolean().optional() }).optional(),
      joins: z.array(join).optional(),
    })
    .refine((j) => (j.on === undefined) !== (j.using === undefined), {
      message: 'A join needs exactly one of on or using',
    })
);

// `fields` is the current keyword; `dimensions` is its older synonym. Both parse to `dimensions`.
const fieldsAsDimensions = (v: unknown) => {
  if (!v || typeof v !== 'object' || Array.isArray(v) || !('fields' in v) || 'dimensions' in v) return v;
  const { fields, ...rest } = v as Record<string, unknown>;
  return { ...rest, dimensions: fields };
};

export const metricViewSchema = z.preprocess(
  fieldsAsDimensions,
  z
    .strictObject({
      version: z.preprocess((v) => (typeof v === 'number' ? v.toFixed(1) : v), z.enum(['1.1', '0.1'])).default('1.1'),
      source: text,
      comment: text.optional(),
      parameters: z.unknown().optional(),
      filter: text.optional(),
      joins: z.array(join).optional(),
      dimensions: z.array(z.strictObject(field)).default([]),
      measures: z
        .array(
          z.strictObject({
            ...field,
            window: z.array(windowSpec).min(1).optional(),
            partition: z
              .strictObject({ include: z.array(text).min(1), outer_aggregate: z.enum(['avg', 'sum', 'min', 'max']) })
              .optional(),
          })
        )
        .default([]),
      materialization: z.unknown().optional(),
    })
    .refine((v) => v.dimensions.length + v.measures.length > 0, { message: 'Add at least one field or measure' })
);

export type MetricView = z.infer<typeof metricViewSchema>;

/** Columns and declared primary key of a source table, keyed by lowercase full name. */
export type SourceProfiles = Record<string, { columns: { name: string }[]; primaryKey: string[] }>;

export interface MetricViewIssue {
  severity: 'error' | 'warning';
  message: string;
  path: (string | number)[];
  line?: number;
}

const ID = '(?:[A-Za-z_]\\w*|`(?:[^`]|``)+`)';
const CHAIN = new RegExp(`(?<![\\w.\`])${ID}(?:\\s*\\.\\s*${ID})+(?![\\w\`(])`, 'g');
// AGG() is the older spelling of MEASURE() inside a measure expression.
const MEASURE_REF = new RegExp(`\\b(?:MEASURE|AGG)\\s*\\(\\s*(${ID})\\s*\\)`, 'gi');
const unquote = (id: string) => (id.startsWith('`') ? id.slice(1, -1).replace(/``/g, '`') : id).toLowerCase();
const splitChain = (chain: string) => (chain.match(new RegExp(ID, 'g')) ?? []).map(unquote);
// Blanks string literal contents, keeping offsets, so names inside strings are not treated as references.
const stripLiterals = (expr: string) =>
  expr.replace(/'(?:[^'\\]|\\.|'')*'|"(?:[^"\\]|\\.)*"/g, (m) => `${m[0]}${' '.repeat(m.length - 2)}${m[0]}`);

interface JoinNode {
  join: Join;
  path: (string | number)[];
  chain: string[];
}

function flattenJoins(joins: Join[] | undefined, path: (string | number)[], parent: string[]): JoinNode[] {
  return (joins ?? []).flatMap((join, i) => {
    const here = [...path, 'joins', i];
    const chain = [...parent, join.name.toLowerCase()];
    return [{ join, path: here, chain }, ...flattenJoins(join.joins, here, chain)];
  });
}

const isTableName = (source: string) => new RegExp(`^${ID}(\\.${ID}){2}$`).test(source.trim());
const tableKey = (source: string) => splitChain(source).join('.');

/** Checks that the schema cannot express: names, references, columns and join keys. */
export function semanticIssues(view: MetricView, profiles?: SourceProfiles): MetricViewIssue[] {
  const issues: MetricViewIssue[] = [];
  const error = (path: (string | number)[], message: string) => issues.push({ severity: 'error', message, path });
  const warn = (path: (string | number)[], message: string) => issues.push({ severity: 'warning', message, path });

  const seen = new Map<string, string>();
  for (const kind of ['dimensions', 'measures'] as const) {
    view[kind].forEach((f, i) => {
      const key = f.name.toLowerCase();
      if (seen.has(key)) error([kind, i, 'name'], `Name "${f.name}" is already used by a ${seen.get(key)}`);
      else seen.set(key, kind === 'dimensions' ? 'dimension' : 'measure');
    });
  }

  if (view.version === '0.1') {
    const semantic = ['comment', 'synonyms', 'display_name', 'format'] as const;
    if (view.comment) error(['comment'], 'comment needs version 1.1');
    for (const kind of ['dimensions', 'measures'] as const) {
      view[kind].forEach((f, i) => {
        for (const k of semantic) if (f[k] !== undefined) error([kind, i, k], `${k} needs version 1.1`);
      });
    }
  }

  const measureNames = new Set(view.measures.map((m) => m.name.toLowerCase()));
  const isDimension = (name: string) => view.dimensions.some((d) => d.name.toLowerCase() === name.toLowerCase());
  view.measures.forEach((m, i) => {
    if (m.partition) {
      warn(['measures', i, 'partition'], 'partition is not in the documented spec and can change');
      for (const name of m.partition.include)
        if (!isDimension(name)) error(['measures', i, 'partition'], `Partition field "${name}" is not a dimension`);
    }
    if (m.window) {
      for (const [w, spec] of m.window.entries()) {
        if (!isDimension(spec.order))
          error(['measures', i, 'window', w, 'order'], `Window order "${spec.order}" is not a dimension`);
      }
    }
    for (const [, ref] of m.expr.matchAll(MEASURE_REF)) {
      const name = unquote(ref ?? '');
      if (name === m.name.toLowerCase()) error(['measures', i, 'expr'], 'A measure cannot reference itself');
      else if (!measureNames.has(name)) error(['measures', i, 'expr'], `MEASURE(${ref}) does not match a measure`);
      else if (/\s/.test(name) && !ref?.startsWith('`'))
        error(['measures', i, 'expr'], `Quote names with spaces: MEASURE(\`${ref}\`)`);
    }
  });
  view.dimensions.forEach((d, i) => {
    if (MEASURE_REF.test(d.expr)) error(['dimensions', i, 'expr'], 'Dimensions cannot use MEASURE()');
    MEASURE_REF.lastIndex = 0;
  });

  const nodes = flattenJoins(view.joins, [], []);
  const byChain = new Map(nodes.map((n) => [n.chain.join('.'), n]));
  const aliases = new Map<string, JoinNode>();
  for (const n of nodes) {
    const alias = n.join.name.toLowerCase();
    if (alias === 'source') error([...n.path, 'name'], '"source" is reserved for the fact table');
    else if (aliases.has(alias)) error([...n.path, 'name'], `Join name "${n.join.name}" is used twice`);
    else aliases.set(alias, n);
  }

  const profileOf = (source: string) => (isTableName(source) ? profiles?.[tableKey(source)] : undefined);
  const columnsOf = (source: string) => {
    const p = profileOf(source);
    return p ? new Set(p.columns.map((c) => c.name.toLowerCase())) : undefined;
  };
  const factColumns = columnsOf(view.source);

  if (profiles) {
    for (const [path, source] of [
      [['source'], view.source] as const,
      ...nodes.map((n) => [[...n.path, 'source'], n.join.source] as const),
    ]) {
      if (!isTableName(source)) warn([...path], 'Columns are not checked for a query source');
      else if (!profileOf(source)) warn([...path], `${source} is not a project source, so its columns are not checked`);
    }
  }

  for (const n of nodes) {
    if (n.chain.length === 1 && factColumns) {
      const alias = n.chain[0] ?? '';
      const clash = [...factColumns].find((c) => c.startsWith(alias));
      if (clash)
        warn(
          [...n.path, 'name'],
          `Join name "${n.join.name}" is a prefix of fact column ${clash}. Use dim_${n.join.name}.`
        );
    }
  }

  const checkColumn = (path: (string | number)[], table: string, column: string, alias: string) => {
    const cols = columnsOf(table);
    if (cols && !cols.has(column)) error(path, `Column ${column} does not exist in ${alias} (${table})`);
  };

  // Expressions address joined tables by the full chain from the fact table: a.b.column.
  const checkExpr = (path: (string | number)[], expr: string) => {
    for (const [chain] of stripLiterals(expr).matchAll(CHAIN)) {
      const parts = splitChain(chain);
      const head = parts[0] ?? '';
      // Inside a measure, a field name wins over a join name, so customer.c_custkey reads the field Customer.
      if (path[0] === 'measures' && aliases.has(head) && isDimension(head))
        error(
          path,
          `"${head}" is a field and a join name, so ${chain} does not resolve. Rename the field or the join.`
        );
      if (head === 'source') {
        checkColumn(path, view.source, parts[1] ?? '', 'source');
        continue;
      }
      let depth = 0;
      while (depth < parts.length - 1 && byChain.has(parts.slice(0, depth + 1).join('.'))) depth++;
      if (depth > 0) {
        const node = byChain.get(parts.slice(0, depth).join('.'));
        if (node) checkColumn(path, node.join.source, parts[depth] ?? '', parts.slice(0, depth).join('.'));
        continue;
      }
      const nested = aliases.get(head);
      if (nested && nested.chain.length > 1)
        error(path, `Use the full join path ${[...nested.chain, ...parts.slice(1)].join('.')} instead of ${chain}`);
    }
  };

  if (view.filter) checkExpr(['filter'], view.filter);
  for (const kind of ['dimensions', 'measures'] as const)
    view[kind].forEach((f, i) => checkExpr([kind, i, 'expr'], f.expr));

  // Join conditions address the parent and the joined table by their own names.
  for (const n of nodes) {
    const alias = n.join.name.toLowerCase();
    const parent = n.chain.length > 1 ? byChain.get(n.chain.slice(0, -1).join('.')) : undefined;
    const parentAlias = parent ? parent.join.name.toLowerCase() : 'source';
    const parentSource = parent ? parent.join.source : view.source;
    const keyCols: string[] = [];
    if (n.join.using) {
      for (const c of n.join.using.map(unquote)) {
        checkColumn([...n.path, 'using'], parentSource, c, parentAlias);
        checkColumn([...n.path, 'using'], n.join.source, c, alias);
        keyCols.push(c);
      }
    } else {
      for (const [chain] of stripLiterals(n.join.on ?? '').matchAll(CHAIN)) {
        const [head, col = ''] = splitChain(chain);
        if (head === alias) {
          checkColumn([...n.path, 'on'], n.join.source, col, alias);
          keyCols.push(col);
        } else if (head === parentAlias) checkColumn([...n.path, 'on'], parentSource, col, parentAlias);
        else error([...n.path, 'on'], `${chain} must reference ${parentAlias} or ${alias}`);
      }
    }
    const profile = profileOf(n.join.source);
    if (!profile || n.join.rely?.at_most_one_match || n.join.cardinality === 'one_to_many') continue;
    if (!profile.primaryKey.length)
      warn([...n.path, 'name'], `${n.join.source} declares no primary key, so a many-to-one join cannot be confirmed`);
    else if (!profile.primaryKey.every((k) => keyCols.includes(k.toLowerCase())))
      warn(
        [...n.path, 'name'],
        `Join keys do not cover the primary key (${profile.primaryKey.join(', ')}) of ${n.join.source}. Rows can be counted twice.`
      );
  }
  return issues;
}

/** Parses and validates YAML text. Issues carry 1-based line numbers. */
export function validateMetricView(
  yamlText: string,
  profiles?: SourceProfiles
): { view?: MetricView; issues: MetricViewIssue[] } {
  const lineCounter = new LineCounter();
  // YAML 1.1 matches the engine: unquoted on, yes and no are booleans.
  const doc = parseDocument(yamlText, { version: '1.1', lineCounter, prettyErrors: false, uniqueKeys: true });
  const syntax = [...doc.errors, ...doc.warnings];
  if (syntax.length)
    return {
      issues: syntax.map((e) => ({
        severity: 'error',
        message: e.message.split('\n')[0] ?? e.message,
        path: [],
        line: lineCounter.linePos(e.pos[0]).line,
      })),
    };

  // Point at the key of a mapping entry, not its value, which can start on the next line.
  const startOf = (path: (string | number)[]) => {
    const parent = doc.getIn(path.slice(0, -1), true);
    const last = path[path.length - 1];
    const node = isMap(parent)
      ? parent.items.find((p) => isScalar(p.key) && p.key.value === last)?.key
      : doc.getIn(path, true);
    return (node as { range?: [number, number, number] } | undefined)?.range?.[0];
  };
  const fieldsKey = doc.has('fields') ? 'fields' : 'dimensions';
  const lineOf = (raw: (string | number)[]) => {
    const path = raw[0] === 'dimensions' ? [fieldsKey, ...raw.slice(1)] : raw;
    for (let n = path.length; n > 0; n--) {
      const start = startOf(path.slice(0, n));
      if (start !== undefined) return lineCounter.linePos(start).line;
    }
    return 1;
  };
  const locate = (issues: MetricViewIssue[]) => issues.map((i) => ({ ...i, line: lineOf(i.path) }));

  const parsed = metricViewSchema.safeParse(doc.toJS());
  if (!parsed.success)
    return {
      issues: locate(
        parsed.error.issues.map((i) => {
          const path = i.path.map((p) => (typeof p === 'number' ? p : String(p)));
          if (path[0] === 'dimensions') path[0] = fieldsKey;
          const where = path.length ? `${path.join('.')}: ` : '';
          const message =
            i.code === 'unrecognized_keys' && i.keys.includes('true')
              ? `Quote the join key as 'on':`
              : `${where}${i.message}`;
          return { severity: 'error', message, path };
        })
      ),
    };
  return { view: parsed.data, issues: locate(semanticIssues(parsed.data, profiles)) };
}

/** Renders a view as YAML 1.1, so keys and values such as on are quoted. Uses the current `fields` keyword. */
export function renderMetricView(view: MetricView): string {
  const { dimensions, measures, materialization, ...head } = view;
  const out = {
    ...head,
    ...(dimensions.length ? { fields: dimensions } : {}),
    ...(measures.length ? { measures } : {}),
    ...(materialization === undefined ? {} : { materialization }),
  };
  return stringify(out, { version: '1.1', lineWidth: 0 });
}

/** Rewrites full join paths (a.b.column) to the joined table's own name (b.column), for plain SQL. */
export function toDirectAliases(view: MetricView, expr: string): string {
  const chains = new Set(flattenJoins(view.joins, [], []).map((n) => n.chain.join('.')));
  const stripped = stripLiterals(expr);
  let out = '';
  let last = 0;
  for (const m of stripped.matchAll(CHAIN)) {
    const ids = m[0].match(new RegExp(ID, 'g')) ?? [];
    const parts = ids.map(unquote);
    let depth = 0;
    while (depth < parts.length - 1 && chains.has(parts.slice(0, depth + 1).join('.'))) depth++;
    if (depth < 2) continue;
    out += expr.slice(last, m.index) + [ids[depth - 1], ...ids.slice(depth)].join('.');
    last = m.index + m[0].length;
  }
  return out + expr.slice(last);
}
