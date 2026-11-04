import type { PermissionCheck } from '../../shared/readiness';
import { quoteId, quoteName } from '../readiness/profile';

type Securable = 'CATALOG' | 'SCHEMA' | 'TABLE';

export const grant = (privilege: string, type: Securable, name: string, principal: string) =>
  `GRANT ${privilege} ON ${type} ${quoteName(name)} TO ${quoteId(principal)};`;

const parts = (table: string) => {
  const [c, s] = table.split('.');
  return { catalog: c, schema: `${c}.${s}` };
};

const readGrants = (table: string, principal: string) => {
  const { catalog, schema } = parts(table);
  return [
    grant('USE CATALOG', 'CATALOG', catalog, principal),
    grant('USE SCHEMA', 'SCHEMA', schema, principal),
    grant('SELECT', 'TABLE', table, principal),
  ];
};

/** Result of `SELECT 1 FROM table LIMIT 0` as the user: the real proof of read access. */
export function selectCheck(table: string, principal: string, error: string | null): PermissionCheck {
  const base = { id: `select:${table}`, group: 'sources' as const, label: `Read ${table}` };
  if (!error) return { ...base, status: 'pass', detail: 'USE CATALOG, USE SCHEMA and SELECT work.', grants: [] };
  const m = /does not have ([A-Z][A-Z _]*?) on (Catalog|Schema|Table|View) '([^']+)'/i.exec(error);
  if (m) {
    const type = (m[2].toUpperCase() === 'VIEW' ? 'TABLE' : m[2].toUpperCase()) as Securable;
    return {
      ...base,
      status: 'fail',
      detail: `Missing ${m[1].toUpperCase()} on ${m[3]}.`,
      grants: [grant(m[1].toUpperCase(), type, m[3], principal)],
    };
  }
  const code = /\b([A-Z][A-Z_]{4,})\b/.exec(error)?.[1];
  return {
    ...base,
    status: 'fail',
    detail: `The table cannot be read${code ? ` (${code})` : ''}. It may not exist, or a privilege is missing.`,
    grants: readGrants(table, principal),
  };
}

/** Ownership and MODIFY come from information_schema, which lists direct and group grants. */
export function fixCheck(
  table: string,
  principal: string,
  found: { owner: boolean; modify: boolean } | null
): PermissionCheck {
  const base = { id: `fix:${table}`, group: 'fixes' as const, label: `Apply fixes on ${table}` };
  if (found?.owner)
    return { ...base, status: 'pass', detail: 'You own the table: comments and keys can be applied.', grants: [] };
  if (found?.modify)
    return {
      ...base,
      status: 'warn',
      detail: 'MODIFY found: comments can be applied. Keys need the table owner.',
      grants: [],
    };
  return {
    ...base,
    status: 'warn',
    detail:
      'Not found: no ownership or MODIFY grant. Comments need MODIFY, keys need the owner. Inherited grants are not listed.',
    grants: [grant('MODIFY', 'TABLE', table, principal)],
  };
}

export function sandboxCheck(schema: string | null, principal: string, canCreate: boolean): PermissionCheck {
  const base = { id: 'sandbox', group: 'sandbox' as const, label: 'Create views in the sandbox schema' };
  if (!schema)
    return {
      ...base,
      status: 'fail',
      detail:
        'No sandbox schema is set. The app admin sets GSB_SANDBOX_SCHEMA so validations and pattern tests can run.',
      grants: [],
    };
  if (canCreate) return { ...base, status: 'pass', detail: `You can create views in ${schema}.`, grants: [] };
  const catalog = schema.split('.')[0];
  return {
    ...base,
    status: 'warn',
    detail: `Not found: CREATE TABLE on ${schema}. Validations and pattern tests create temporary views there.`,
    grants: [
      grant('USE CATALOG', 'CATALOG', catalog, principal),
      grant('USE SCHEMA', 'SCHEMA', schema, principal),
      grant('CREATE TABLE', 'SCHEMA', schema, principal),
    ],
  };
}
