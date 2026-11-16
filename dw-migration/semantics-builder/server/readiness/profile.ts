import type { ReadinessCheck, Recommendation } from '../../shared/readiness';
import type { FixEffect } from './score';

export interface ColumnProfile {
  name: string;
  type: string;
  comment: string;
}

export interface ForeignKey {
  columns: string[];
  references: string;
  refColumns: string[];
}

export interface TableProfile {
  fullName: string;
  comment: string;
  columns: ColumnProfile[];
  primaryKey: string[];
  foreignKeys: ForeignKey[];
}

const pct = (n: number, d: number) => (d ? Math.round((100 * n) / d) : 0);

export function checksFor(p: TableProfile): ReadinessCheck[] {
  const commented = p.columns.filter((c) => c.comment).length;
  const ratio = p.columns.length ? commented / p.columns.length : 0;
  const stringDates = p.columns
    .filter((c) => /(date|time|_dt$|_ts$)/i.test(c.name) && /^string$/i.test(c.type))
    .map((c) => c.name);
  return [
    {
      id: 'accessible',
      label: 'You can read the table',
      status: 'pass',
      detail: `${p.columns.length} columns`,
    },
    {
      id: 'table_comment',
      label: 'Table has a description',
      status: p.comment ? 'pass' : 'fail',
      detail: p.comment
        ? p.comment.slice(0, 200)
        : 'No table comment. Genie and metric views use it to understand the table.',
    },
    {
      id: 'column_comments',
      label: 'Columns have descriptions',
      status: ratio >= 0.8 ? 'pass' : ratio >= 0.3 ? 'warn' : 'fail',
      detail: `${commented} of ${p.columns.length} columns (${pct(commented, p.columns.length)}%) have a comment.`,
    },
    {
      id: 'primary_key',
      label: 'Primary key is declared',
      status: p.primaryKey.length ? 'pass' : 'warn',
      detail: p.primaryKey.length ? p.primaryKey.join(', ') : 'No primary key. Joins to this table are not documented.',
    },
    {
      id: 'foreign_keys',
      label: 'Foreign keys are declared',
      status: p.foreignKeys.length ? 'pass' : 'warn',
      detail: p.foreignKeys.length
        ? p.foreignKeys.map((f) => `${f.columns.join(', ')} -> ${f.references}`).join('; ')
        : 'No foreign keys declared. Fact tables need them to document joins.',
    },
    {
      id: 'date_types',
      label: 'Dates use date or timestamp types',
      status: stringDates.length ? 'warn' : 'pass',
      detail: stringDates.length
        ? `Stored as text: ${stringDates.join(', ')}. Time grains need a date or timestamp type.`
        : 'No date columns stored as text.',
    },
  ];
}

export function inaccessibleChecks(message: string): ReadinessCheck[] {
  const code = /\b([A-Z][A-Z_]{4,})\b/.exec(message)?.[1];
  return [
    {
      id: 'accessible',
      label: 'You can read the table',
      status: 'fail',
      detail: `You cannot read this table, or it does not exist${code ? ` (${code})` : ''}.`,
    },
  ];
}

export const quoteId = (s: string) => `\`${s.replace(/`/g, '``')}\``;
export const quoteName = (fullName: string) => fullName.split('.').map(quoteId).join('.');
// The allowlist masks strings with backslash escapes, so escape the backslash first.
export const sqlString = (s: string) =>
  `'${s
    .replace(/\p{Cc}/gu, ' ')
    .replace(/\\/g, '\\\\')
    .replace(/'/g, "\\'")}'`;

const constraintName = (table: string, suffix: string) =>
  `${table
    .split('.')
    .pop()!
    .replace(/[^A-Za-z0-9_]/g, '_')}_${suffix}`.slice(0, 120);

/** NOT NULL on each key column, then the informational primary key. */
export const pkStatements = (fullName: string, columns: string[]) => [
  ...columns.map((c) => `ALTER TABLE ${quoteName(fullName)} ALTER COLUMN ${quoteId(c)} SET NOT NULL`),
  `ALTER TABLE ${quoteName(fullName)} ADD CONSTRAINT ${quoteId(constraintName(fullName, 'pk'))} PRIMARY KEY (${columns.map(quoteId).join(', ')})`,
];

export const fkStatement = (fullName: string, references: string, columns: string[], refColumns: string[]) =>
  `ALTER TABLE ${quoteName(fullName)} ADD CONSTRAINT ${quoteId(constraintName(fullName, `${references.split('.').pop()}_fk`))} FOREIGN KEY (${columns.map(quoteId).join(', ')}) REFERENCES ${quoteName(references)} (${refColumns.map(quoteId).join(', ')})`;

export interface Proposal {
  tableComment: string | null;
  columnComments: { column: string; comment: string }[];
  primaryKey: string[] | null;
  foreignKeys: ForeignKey[];
}

export type NewRecommendation = Pick<Recommendation, 'kind' | 'title' | 'rationale' | 'statements'> & {
  effect: FixEffect;
};

/**
 * Turns model proposals into SQL. The model never writes SQL: names are checked against the
 * real table profiles and every literal and identifier is quoted here.
 */
export function buildRecommendations(
  p: TableProfile,
  proposal: Proposal,
  others: Map<string, TableProfile>,
  /** Definitions from the project dictionary, by lowercase column name. They win over the model's text. */
  dictionary: Map<string, { text: string; entry: string }> = new Map()
): NewRecommendation[] {
  const table = quoteName(p.fullName);
  const colIndex = (t: TableProfile) => new Map(t.columns.map((c) => [c.name.toLowerCase(), c]));
  const cols = colIndex(p);
  const resolve = (index: Map<string, ColumnProfile>, names: string[]) => {
    const found = names.map((n) => index.get(n.trim().toLowerCase()));
    return found.every(Boolean) && new Set(found).size === found.length ? found.map((c) => c!.name) : null;
  };
  const out: NewRecommendation[] = [];

  const tableComment = proposal.tableComment?.trim();
  if (!p.comment && tableComment) {
    out.push({
      kind: 'table_comment',
      title: `Describe ${p.fullName}`,
      rationale: 'A table description helps Genie and metric view authors choose the right table.',
      statements: [`COMMENT ON TABLE ${table} IS ${sqlString(tableComment)}`],
      effect: { tableComment: true },
    });
  }

  const seen = new Set<string>();
  const fromDictionary: string[] = [];
  const entries: string[] = [];
  for (const c of p.columns) {
    const d = dictionary.get(c.name.toLowerCase());
    if (!d || c.comment || !d.text.trim()) continue;
    seen.add(c.name);
    entries.push(d.entry);
    fromDictionary.push(`COMMENT ON COLUMN ${table}.${quoteId(c.name)} IS ${sqlString(d.text.trim())}`);
  }
  if (fromDictionary.length) {
    out.push({
      kind: 'column_comments',
      title: `Describe ${fromDictionary.length} column${fromDictionary.length === 1 ? '' : 's'} of ${p.fullName} from the dictionary`,
      rationale: `From the project's metric dictionary: ${entries.join(', ')}. The team's own definitions become the column descriptions.`,
      statements: fromDictionary,
      effect: { columns: [...seen] },
    });
  }

  const columnStatements = proposal.columnComments.flatMap(({ column, comment }) => {
    const c = cols.get(column.trim().toLowerCase());
    const text = comment.trim();
    if (!c || c.comment || !text || seen.has(c.name)) return [];
    seen.add(c.name);
    return [`COMMENT ON COLUMN ${table}.${quoteId(c.name)} IS ${sqlString(text)}`];
  });
  if (columnStatements.length) {
    out.push({
      kind: 'column_comments',
      title: `Describe ${columnStatements.length} columns of ${p.fullName}`,
      rationale: 'Column descriptions become the default descriptions of dimensions and measures.',
      statements: columnStatements,
      effect: { columns: [...seen].filter((c) => !fromDictionary.some((s) => s.includes(quoteId(c)))) },
    });
  }

  const pk = !p.primaryKey.length && proposal.primaryKey?.length ? resolve(cols, proposal.primaryKey) : null;
  if (pk) {
    out.push({
      kind: 'primary_key',
      title: `Declare the primary key of ${p.fullName}`,
      rationale: `Declares ${pk.join(', ')} as the unique key. Key columns must not contain NULL values, so the columns are set to NOT NULL first. The key is informational and is not enforced.`,
      statements: pkStatements(p.fullName, pk),
      effect: { primaryKey: pk },
    });
  }

  const existing = new Set(p.foreignKeys.map((f) => `${f.columns.join(',')}>${f.references}`.toLowerCase()));
  for (const fk of proposal.foreignKeys) {
    const ref = others.get(fk.references.trim().toLowerCase());
    const local = resolve(cols, fk.columns);
    const remote = ref ? resolve(colIndex(ref), fk.refColumns) : null;
    if (!ref || !local || !remote || local.length !== remote.length) continue;
    const key = `${local.join(',')}>${ref.fullName}`.toLowerCase();
    if (existing.has(key)) continue;
    existing.add(key);
    out.push({
      kind: 'foreign_key',
      title: `Link ${p.fullName} to ${ref.fullName}`,
      rationale: `Documents the join ${local.join(', ')} -> ${ref.fullName} (${remote.join(', ')}). ${ref.fullName} needs a primary key on ${remote.join(', ')} first. The key is informational and is not enforced.`,
      statements: [fkStatement(p.fullName, ref.fullName, local, remote)],
      effect: { foreignKey: { columns: local, references: ref.fullName, refColumns: remote } },
    });
  }
  return out;
}

const ID_PART = '`(?:[^`]|``)*`';
const COMMENT_ON = new RegExp(
  `^(COMMENT ON (?:TABLE ${ID_PART}(?:\\.${ID_PART}){2}|COLUMN ${ID_PART}(?:\\.${ID_PART}){3}) IS )'(?:[^'\\\\]|\\\\.)*'$`,
  's'
);

/** A generated COMMENT ON statement with the user's text instead. Throws for any other statement. */
export function withComment(statement: string, text: string): string {
  const prefix = COMMENT_ON.exec(statement)?.[1];
  if (!prefix) throw new Error('Only a comment statement can take edited text.');
  const t = text.trim();
  if (!t || t.length > 1000) throw new Error('A comment needs 1 to 1000 characters.');
  return `${prefix}${sqlString(t)}`;
}
