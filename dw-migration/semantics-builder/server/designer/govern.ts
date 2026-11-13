import { quoteId, quoteName } from '../readiness/profile';

/** The one statement for a governance action on the promoted view. Read access only; the server picks the view. */
export function governStatement(action: 'owner' | 'grant' | 'revoke', target: string, principal: string): string {
  const view = quoteName(target);
  const who = quoteId(principal.trim());
  if (action === 'owner') return `ALTER VIEW ${view} OWNER TO ${who}`;
  return action === 'grant' ? `GRANT SELECT ON VIEW ${view} TO ${who}` : `REVOKE SELECT ON VIEW ${view} FROM ${who}`;
}
