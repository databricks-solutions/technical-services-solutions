import type { FixEdits, FixRow, Recommendation } from '../../shared/readiness';
import { fkStatement, pkStatements, withComment } from './profile';
import type { TableProfile } from './profile';
import type { FixEffect } from './score';

const ids = (s: string) => [...s.matchAll(/`((?:[^`]|``)*)`/g)].map((m) => m[1].replace(/``/g, '`'));
const COMMENT = /^COMMENT ON (TABLE|COLUMN) (.+?) IS '((?:[^'\\]|\\.)*)'$/s;
const PK = /PRIMARY KEY \((.*)\)$/s;
const FK = /FOREIGN KEY \((.*?)\) REFERENCES (.+?) \((.*)\)$/s;

export const commentOf = (statement: string) => {
  const m = COMMENT.exec(statement);
  if (!m) return null;
  const parts = ids(m[2]);
  return {
    table: parts.slice(0, 3).join('.'),
    column: m[1] === 'COLUMN' ? (parts[3] ?? null) : null,
    text: m[3].replace(/\\(.)/g, '$1'),
  };
};

const optionsOf = (p: TableProfile | undefined) => (p?.columns ?? []).map((c) => ({ name: c.name, type: c.type }));
const find = (profiles: Map<string, TableProfile>, name: string) =>
  profiles.get(name) ?? [...profiles.values()].find((p) => p.fullName.toLowerCase() === name.toLowerCase());

/** The fix as editable rows, with the current value from the table profile. */
export function fixRows(
  kind: Recommendation['kind'],
  fullName: string | null,
  statements: string[],
  profiles: Map<string, TableProfile>
): FixRow[] {
  if (kind === 'table_comment' || kind === 'column_comments')
    return statements.flatMap((s, index) => {
      const c = commentOf(s);
      if (!c) return [];
      const p = find(profiles, c.table);
      const col = c.column ? p?.columns.find((x) => x.name.toLowerCase() === c.column!.toLowerCase()) : undefined;
      return [
        {
          kind: 'comment' as const,
          index,
          table: c.table,
          column: c.column,
          type: col?.type ?? null,
          current: (c.column ? col?.comment : p?.comment) ?? '',
          proposed: c.text,
        },
      ];
    });
  if (!fullName) return [];
  const last = statements.at(-1) ?? '';
  const p = find(profiles, fullName);
  if (kind === 'primary_key') {
    const m = PK.exec(last);
    return m
      ? [
          {
            kind: 'key',
            table: fullName,
            columns: ids(m[1]),
            options: optionsOf(p),
            references: null,
            refColumns: [],
            refOptions: [],
          },
        ]
      : [];
  }
  const m = FK.exec(last);
  if (!m) return [];
  const references = ids(m[2]).join('.');
  return [
    {
      kind: 'key',
      table: fullName,
      columns: ids(m[1]),
      options: optionsOf(p),
      references,
      refColumns: ids(m[3]),
      refOptions: optionsOf(find(profiles, references)),
    },
  ];
}

function resolve(p: TableProfile | undefined, names: string[], what: string) {
  if (!p) throw new Error(`The columns of ${what} are not known. Assess the sources again.`);
  const found = names.map((n) => p.columns.find((c) => c.name.toLowerCase() === n.trim().toLowerCase())?.name);
  if (!found.length || found.some((c) => !c) || new Set(found).size !== found.length)
    throw new Error(`Pick distinct columns of ${what}.`);
  return found as string[];
}

/**
 * The statements that run, rebuilt by the server from the user's edits, and what they change in the profile.
 * Comment text goes through withComment; key columns must be real columns of the tables.
 */
export function finalFix(
  kind: Recommendation['kind'],
  fullName: string | null,
  statements: string[],
  edits: FixEdits,
  profiles: Map<string, TableProfile>
): { statements: string[]; effect: FixEffect | null } {
  if (kind === 'table_comment' || kind === 'column_comments') {
    const skip = new Set(edits.skip ?? []);
    const kept = statements.flatMap((s, i) => {
      if (skip.has(i)) return [];
      const text = edits.comments?.[i];
      return [text == null ? s : withComment(s, text)];
    });
    if (!kept.length) throw new Error('Keep at least one change, or reject the fix.');
    if (!edits.skip?.length && !edits.comments?.some((c) => c != null)) return { statements, effect: null };
    if (kind === 'table_comment') return { statements: kept, effect: { tableComment: true } };
    return { statements: kept, effect: { columns: kept.flatMap((s) => commentOf(s)?.column ?? []) } };
  }
  if (!edits.key) return { statements, effect: null };
  if (!fullName) throw new Error('This fix has no table.');
  const table = find(profiles, fullName);
  const columns = resolve(table, edits.key.columns, fullName);
  if (kind === 'primary_key') return { statements: pkStatements(fullName, columns), effect: { primaryKey: columns } };
  const m = FK.exec(statements.at(-1) ?? '');
  if (!m) throw new Error('This fix is not a foreign key.');
  const references = ids(m[2]).join('.');
  const refColumns = resolve(find(profiles, references), edits.key.refColumns ?? [], references);
  if (refColumns.length !== columns.length) throw new Error('Pick as many referenced columns as key columns.');
  return {
    statements: [fkStatement(fullName, references, columns, refColumns)],
    effect: { foreignKey: { columns, references, refColumns } },
  };
}

/**
 * A comment fix without the statements for one target (a column, or the table when column is null).
 * Returns null when the fix has none for it.
 */
export function withoutTarget(
  kind: Recommendation['kind'],
  statements: string[],
  target: { column: string | null } | { index: number }
): { statements: string[]; effect: FixEffect } | null {
  if (kind !== 'table_comment' && kind !== 'column_comments') return null;
  const drop = (s: string, i: number) => {
    if ('index' in target) return i === target.index;
    const c = commentOf(s);
    return (
      !!c && (target.column === null ? c.column === null : c.column?.toLowerCase() === target.column.toLowerCase())
    );
  };
  const kept = statements.filter((s, i) => !drop(s, i));
  if (kept.length === statements.length) return null;
  return {
    statements: kept,
    effect:
      kind === 'table_comment' ? { tableComment: true } : { columns: kept.flatMap((s) => commentOf(s)?.column ?? []) },
  };
}
