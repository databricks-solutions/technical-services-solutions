/**
 * The metric dictionary format: one definition of the columns, used by the template downloads and by the
 * importer, so they cannot drift apart.
 */
export const DICTIONARY_KINDS = ['metric', 'dimension', 'term'] as const;
export type DictionaryKind = (typeof DICTIONARY_KINDS)[number];

export interface DictionaryColumn {
  key: string;
  header: string;
  required: boolean;
  help: string;
  /** Other headers that mean the same, matched without case. */
  aliases: string[];
  /** The sections where the column applies. */
  kinds: DictionaryKind[];
}

const ALL: DictionaryKind[] = ['metric', 'dimension', 'term'];
const FIELDS: DictionaryKind[] = ['metric', 'dimension'];

export const DICTIONARY_COLUMNS: DictionaryColumn[] = [
  {
    key: 'name',
    header: 'name',
    required: true,
    help: 'Business name, for example Net Revenue.',
    aliases: ['metric', 'metric name', 'term', 'field', 'kpi'],
    kinds: ALL,
  },
  {
    key: 'display_name',
    header: 'display_name',
    required: false,
    help: 'Label shown in charts and Genie.',
    aliases: ['display name', 'label', 'title'],
    kinds: FIELDS,
  },
  {
    key: 'definition',
    header: 'definition',
    required: true,
    help: 'What it means, in business words. One or two sentences.',
    aliases: ['description', 'meaning', 'business definition', 'comment'],
    kinds: ALL,
  },
  {
    key: 'formula',
    header: 'formula',
    required: false,
    help: 'How it is computed, in words or SQL.',
    aliases: ['expression', 'calculation', 'sql', 'logic'],
    kinds: FIELDS,
  },
  {
    key: 'aggregation',
    header: 'aggregation',
    required: false,
    help: 'sum, count, count_distinct, avg, min, max, ratio or other.',
    aliases: ['agg', 'aggregate'],
    kinds: ['metric'],
  },
  {
    key: 'format',
    header: 'format',
    required: false,
    help: 'currency:USD, percentage, number or date.',
    aliases: ['unit', 'display format'],
    kinds: FIELDS,
  },
  {
    key: 'synonyms',
    header: 'synonyms',
    required: false,
    help: 'Other words users type, separated by ;',
    aliases: ['aliases', 'also known as', 'aka'],
    kinds: ALL,
  },
  {
    key: 'grain',
    header: 'grain',
    required: false,
    help: 'day, week, month, quarter or year.',
    aliases: ['time grain', 'granularity'],
    kinds: ['metric'],
  },
  {
    key: 'source',
    header: 'source',
    required: false,
    help: 'catalog.schema.table.column the value comes from, when known.',
    aliases: ['source column', 'column', 'table'],
    kinds: FIELDS,
  },
  {
    key: 'owner',
    header: 'owner',
    required: false,
    help: 'Person or team that owns the definition.',
    aliases: ['steward', 'data owner'],
    kinds: ALL,
  },
  {
    key: 'status',
    header: 'status',
    required: false,
    help: 'draft, approved or certified. Certified entries lock the name and formula.',
    aliases: ['state', 'certification'],
    kinds: ALL,
  },
];

export const DICTIONARY_SECTIONS: { kind: DictionaryKind; title: string }[] = [
  { kind: 'metric', title: 'Metrics' },
  { kind: 'dimension', title: 'Dimensions' },
  { kind: 'term', title: 'Glossary' },
];

export const columnsFor = (kind: DictionaryKind) => DICTIONARY_COLUMNS.filter((c) => c.kinds.includes(kind));

/** Example rows on TPC-H. A filled row like these passes the best-practice rules. */
export const DICTIONARY_EXAMPLES: Record<DictionaryKind, Record<string, string>[]> = {
  metric: [
    {
      name: 'Net Revenue',
      display_name: 'Net revenue',
      definition: 'Value of the order lines after discounts, before tax.',
      formula: 'SUM(l_extendedprice * (1 - l_discount))',
      aggregation: 'sum',
      format: 'currency:USD',
      synonyms: 'net sales; revenue',
      grain: 'month',
      source: 'samples.tpch.lineitem.l_extendedprice',
      owner: 'Finance analytics',
      status: 'certified',
    },
    {
      name: 'Average Order Value',
      display_name: 'Average order value',
      definition: 'Net revenue divided by the number of distinct orders.',
      formula: 'Net Revenue / NULLIF(Order Count, 0)',
      aggregation: 'ratio',
      format: 'currency:USD',
      synonyms: 'AOV; basket size',
      grain: 'month',
      source: '',
      owner: 'Finance analytics',
      status: 'approved',
    },
  ],
  dimension: [
    {
      name: 'Customer Region',
      display_name: 'Customer region',
      definition: 'Geographic region of the customer who placed the order.',
      formula: 'r_name',
      format: '',
      synonyms: 'region; market',
      source: 'samples.tpch.region.r_name',
      owner: 'Sales operations',
      status: 'approved',
    },
  ],
  term: [
    {
      name: 'Order',
      definition: 'A customer purchase with one or more order lines.',
      synonyms: 'purchase',
      owner: 'Sales operations',
      status: 'approved',
    },
  ],
};

const cell = (v: string) => v.replace(/\|/g, '\\|').replace(/\n/g, ' ');

/** The Markdown template: one pipe table per section, with the example rows. */
export function markdownTemplate(): string {
  const parts = [
    '# Metric dictionary',
    '',
    'Fill one row per entry. Only `name` and `definition` are required. Keep the headers; extra columns are kept as notes.',
    '',
    ...DICTIONARY_COLUMNS.map((c) => `- \`${c.header}\`${c.required ? ' (required)' : ''}: ${c.help}`),
  ];
  for (const s of DICTIONARY_SECTIONS) {
    const cols = columnsFor(s.kind);
    parts.push(
      '',
      `## ${s.title}`,
      '',
      `| ${cols.map((c) => c.header).join(' | ')} |`,
      `| ${cols.map(() => '---').join(' | ')} |`,
      ...DICTIONARY_EXAMPLES[s.kind].map((r) => `| ${cols.map((c) => cell(r[c.key] ?? '')).join(' | ')} |`)
    );
  }
  return `${parts.join('\n')}\n`;
}

export const DICTIONARY_AGGREGATIONS = [
  'sum',
  'count',
  'count_distinct',
  'avg',
  'min',
  'max',
  'ratio',
  'other',
] as const;
export const DICTIONARY_STATUSES = ['draft', 'approved', 'certified'] as const;

/** One imported definition. Unknown columns are kept in notes. */
export interface DictionaryEntry {
  kind: DictionaryKind;
  name: string;
  definition: string;
  display_name?: string;
  formula?: string;
  aggregation?: (typeof DICTIONARY_AGGREGATIONS)[number];
  format?: string;
  synonyms: string[];
  grain?: string;
  source?: string;
  owner?: string;
  status: (typeof DICTIONARY_STATUSES)[number];
  notes: Record<string, string>;
}

/** What an upload would change. Nothing is stored until the user confirms. */
export interface DictionaryPreview {
  fileName: string;
  entries: DictionaryEntry[];
  problems: string[];
  added: string[];
  changed: string[];
  removed: string[];
}
