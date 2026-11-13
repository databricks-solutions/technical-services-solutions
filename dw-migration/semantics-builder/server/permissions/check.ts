import type { PermissionCheck } from '../../shared/readiness';
import { quoteId, quoteName } from '../readiness/profile';

type Securable = 'CATALOG' | 'SCHEMA' | 'TABLE';

export const grant = (privilege: string, type: Securable, name: string, principal: string) =>
  `GRANT ${privilege} ON ${type} ${quoteName(name)} TO ${quoteId(principal)};`;

export interface Identity {
  userName: string;
  groups: string[];
}

export const owns = (owner: string | undefined, who: Identity) =>
  !!owner && (owner === who.userName || who.groups.includes(owner));

/** Who owns a securable, and whether that is the user or one of the user's groups. */
export interface Ownership {
  owner?: string;
  mine: boolean;
}

const askOwner = (owner: string | undefined, fallback: string) => (owner ? `Ask ${owner}` : `Ask ${fallback}`);

/**
 * Unity Catalog shows a user only the tables they have a privilege on, so a table that loads as the
 * user is readable enough to model. A missing SELECT shows when its first query runs as the user.
 */
export function readCheck(table: string, principal: string, r: { error?: string }): PermissionCheck {
  const base = { id: `select:${table}`, group: 'sources' as const, label: `Read ${table}` };
  if (!r.error)
    return { ...base, status: 'pass', detail: 'You can see this table. Queries on it run as you.', grants: [] };
  const [c, s] = table.split('.');
  const code = /\b([A-Z][A-Z_]{4,})\b/.exec(r.error)?.[1];
  return {
    ...base,
    status: 'fail',
    detail: `You cannot see this table${code ? ` (${code})` : ''}. Ask the table owner for these grants.`,
    grants: [
      grant('USE CATALOG', 'CATALOG', c, principal),
      grant('USE SCHEMA', 'SCHEMA', `${c}.${s}`, principal),
      grant('SELECT', 'TABLE', table, principal),
    ],
  };
}

export function fixCheck(table: string, principal: string, o: Ownership): PermissionCheck {
  const base = { id: `fix:${table}`, group: 'fixes' as const, label: `Apply fixes on ${table}` };
  if (o.mine)
    return { ...base, status: 'pass', detail: 'You own the table: comments and keys can be applied.', grants: [] };
  return {
    ...base,
    status: 'warn',
    detail: `${askOwner(o.owner, 'the table owner')} for MODIFY to apply comments. Keys need the owner to apply them.`,
    grants: [grant('MODIFY', 'TABLE', table, principal)],
  };
}

export function sandboxCheck(schema: string | null, principal: string, o: Ownership): PermissionCheck {
  const base = { id: 'sandbox', group: 'sandbox' as const, label: 'Create views in the sandbox schema' };
  if (!schema)
    return {
      ...base,
      status: 'fail',
      detail:
        'No sandbox schema is set. The app admin sets GSB_SANDBOX_SCHEMA so validations and pattern tests can run.',
      grants: [],
    };
  if (o.mine) return { ...base, status: 'pass', detail: `You own ${schema}: views can be created.`, grants: [] };
  const catalog = schema.split('.')[0];
  return {
    ...base,
    status: 'warn',
    detail: `${askOwner(o.owner, 'the schema owner')} for CREATE TABLE on ${schema} if validations fail. Validations and pattern tests create temporary views there.`,
    grants: [
      grant('USE CATALOG', 'CATALOG', catalog, principal),
      grant('USE SCHEMA', 'SCHEMA', schema, principal),
      grant('CREATE TABLE', 'SCHEMA', schema, principal),
    ],
  };
}
