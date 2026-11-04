import type { PermissionCheck } from '../../shared/readiness';
import { SCOPE_MESSAGE, SCOPE_MISSING } from '../api/http';
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

export interface Identity {
  userName: string;
  groups: string[];
}

const PRIVILEGE_SQL: Record<string, { sql: string; type: Securable }> = {
  USE_CATALOG: { sql: 'USE CATALOG', type: 'CATALOG' },
  USE_SCHEMA: { sql: 'USE SCHEMA', type: 'SCHEMA' },
  SELECT: { sql: 'SELECT', type: 'TABLE' },
};

/** True when the user, or one of the user's groups, holds one of the privileges (directly or inherited). */
export const holds = (grants: { principal: string; privileges: string[] }[], who: Identity, wanted: string[]) =>
  grants.some(
    (g) =>
      (g.principal === who.userName || who.groups.includes(g.principal)) &&
      g.privileges.some((p) => p === 'ALL_PRIVILEGES' || wanted.includes(p))
  );

export const owns = (owner: string | undefined, who: Identity) =>
  !!owner && (owner === who.userName || who.groups.includes(owner));

/**
 * Read access from the Unity Catalog API: the table is visible, and USE CATALOG, USE SCHEMA and
 * SELECT are held directly, through a group, or by inheritance. Owners pass.
 */
export function readCheck(
  table: string,
  principal: string,
  r: { error?: string; owner?: boolean; missing: (keyof typeof PRIVILEGE_SQL)[] }
): PermissionCheck {
  const base = { id: `select:${table}`, group: 'sources' as const, label: `Read ${table}` };
  if (r.error && SCOPE_MISSING.test(r.error)) return { ...base, status: 'warn', detail: SCOPE_MESSAGE, grants: [] };
  if (r.error) {
    const code = /\b([A-Z][A-Z_]{4,})\b/.exec(r.error)?.[1];
    return {
      ...base,
      status: 'fail',
      detail: `You cannot see this table${code ? ` (${code})` : ''}. It may not exist, or USE CATALOG or USE SCHEMA is missing.`,
      grants: readGrants(table, principal),
    };
  }
  if (r.owner || !r.missing.length)
    return {
      ...base,
      status: 'pass',
      detail: r.owner ? 'You own the table.' : 'USE CATALOG, USE SCHEMA and SELECT found.',
      grants: [],
    };
  const { catalog, schema } = parts(table);
  const target = { CATALOG: catalog, SCHEMA: schema, TABLE: table };
  return {
    ...base,
    status: 'warn',
    detail: `Not found: ${r.missing.map((m) => PRIVILEGE_SQL[m].sql).join(', ')}. A nested group grant can still allow it.`,
    grants: r.missing.map((m) =>
      grant(PRIVILEGE_SQL[m].sql, PRIVILEGE_SQL[m].type, target[PRIVILEGE_SQL[m].type], principal)
    ),
  };
}

/** Ownership and MODIFY come from the Unity Catalog API, with inherited and group grants. */
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
    detail: 'Not found: no ownership or MODIFY grant. Comments need MODIFY, keys need the owner.',
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
