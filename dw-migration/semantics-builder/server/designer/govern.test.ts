import { describe, expect, it } from 'vitest';
import { checkStatement } from '../sql/allowlist';
import { governStatement } from './govern';

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
