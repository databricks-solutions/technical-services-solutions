import { describe, expect, it } from 'vitest';
import { checkStatement } from '../sql/allowlist';
import { governStatement, tagStatement } from './govern';

describe('governStatement', () => {
  it('builds owner, grant and revoke statements the allowlist accepts', () => {
    const t = 'main.sales.order_metrics';
    expect(governStatement('owner', t, 'data team')).toBe(
      'ALTER VIEW `main`.`sales`.`order_metrics` OWNER TO `data team`'
    );
    expect(governStatement('grant', t, 'a@b.com')).toBe(
      'GRANT SELECT ON VIEW `main`.`sales`.`order_metrics` TO `a@b.com`'
    );
    expect(governStatement('revoke', t, 'a@b.com')).toBe(
      'REVOKE SELECT ON VIEW `main`.`sales`.`order_metrics` FROM `a@b.com`'
    );
    for (const a of ['owner', 'grant', 'revoke'] as const)
      expect(checkStatement(governStatement(a, t, 'x y')).kind).toBe('ddl');
  });
});

describe('tagStatement', () => {
  const t = 'main.sales.order_metrics';
  it('sets and removes view and field tags with statements the allowlist accepts', () => {
    const all = [
      tagStatement(t, { column: null, name: 'domain', value: 'sales' }),
      tagStatement(t, { column: 'Customer Name', name: 'pii', value: 'true' }),
      tagStatement(t, { column: null, name: 'domain', value: null }),
      tagStatement(t, { column: 'Customer Name', name: 'pii', value: "it's" }),
    ];
    expect(all.slice(0, 3)).toEqual([
      "ALTER VIEW `main`.`sales`.`order_metrics` SET TAGS ('domain' = 'sales')",
      "ALTER TABLE `main`.`sales`.`order_metrics` ALTER COLUMN `Customer Name` SET TAGS ('pii' = 'true')",
      "ALTER VIEW `main`.`sales`.`order_metrics` UNSET TAGS ('domain')",
    ]);
    for (const s of all) expect(checkStatement(s).kind).toBe('ddl');
  });
});
