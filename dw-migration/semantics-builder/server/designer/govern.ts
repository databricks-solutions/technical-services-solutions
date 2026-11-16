import { quoteId, quoteName, sqlString } from '../readiness/profile';

/** The one statement for a governance action on the promoted view. Read access only; the server picks the view. */
export function governStatement(action: 'owner' | 'grant' | 'revoke', target: string, principal: string): string {
  const view = quoteName(target);
  const who = quoteId(principal.trim());
  if (action === 'owner') return `ALTER VIEW ${view} OWNER TO ${who}`;
  return action === 'grant' ? `GRANT SELECT ON VIEW ${view} TO ${who}` : `REVOKE SELECT ON VIEW ${view} FROM ${who}`;
}

/** Sets or removes one tag on the promoted view or a field of it. A metric view field takes ALTER TABLE ... ALTER COLUMN. */
export function tagStatement(
  target: string,
  tag: { column: string | null; name: string; value: string | null }
): string {
  const on = tag.column
    ? `ALTER TABLE ${quoteName(target)} ALTER COLUMN ${quoteId(tag.column)}`
    : `ALTER VIEW ${quoteName(target)}`;
  const name = sqlString(tag.name.trim());
  return tag.value === null
    ? `${on} UNSET TAGS (${name})`
    : `${on} SET TAGS (${name} = ${sqlString(tag.value.trim())})`;
}
