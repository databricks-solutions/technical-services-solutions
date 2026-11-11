import { describe, expect, it } from 'vitest';
import { checkStatement } from '../sql/allowlist';
import { certifyStatement } from './certify';

describe('certifyStatement', () => {
  it('sets the governed tag with an allowlisted DDL statement', () => {
    const table = certifyStatement('main.sales.orders', 'MANAGED');
    expect(table).toBe("ALTER TABLE `main`.`sales`.`orders` SET TAGS ('system.certification_status' = 'certified')");
    expect(checkStatement(table).kind).toBe('ddl');
    expect(certifyStatement('main.sales.v', 'VIEW')).toMatch(/^ALTER VIEW /);
  });
});
