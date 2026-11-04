import { describe, expect, it } from 'vitest';
import { fixCheck, grant, holds, readCheck, sandboxCheck } from './check';

describe('grant', () => {
  it('quotes the securable and the principal', () => {
    expect(grant('SELECT', 'TABLE', 'c.s.t', 'a@x.com')).toBe('GRANT SELECT ON TABLE `c`.`s`.`t` TO `a@x.com`;');
  });
});

describe('readCheck', () => {
  it('passes for the owner or when every privilege is held', () => {
    expect(readCheck('c.s.t', 'a@x.com', { owner: true, missing: ['SELECT'] }).status).toBe('pass');
    expect(readCheck('c.s.t', 'a@x.com', { missing: [] })).toMatchObject({ status: 'pass', grants: [] });
  });

  it('lists the GRANT for each missing privilege', () => {
    const c = readCheck('c.s.t', 'a@x.com', { missing: ['USE_SCHEMA', 'SELECT'] });
    expect(c.status).toBe('warn');
    expect(c.grants).toEqual([
      'GRANT USE SCHEMA ON SCHEMA `c`.`s` TO `a@x.com`;',
      'GRANT SELECT ON TABLE `c`.`s`.`t` TO `a@x.com`;',
    ]);
  });

  it('asks for a new sign-in when the token lacks the scope', () => {
    const c = readCheck('c.s.t', 'a@x.com', { error: 'Invalid scope, required scopes: unity-catalog', missing: [] });
    expect(c).toMatchObject({ status: 'warn', grants: [] });
    expect(c.detail).toMatch(/sign in again/);
    const other = readCheck('c.s.t', 'a@x.com', {
      error: 'Provided OAuth token does not have required scopes: unity-catalog',
      missing: [],
    });
    expect(other.status).toBe('warn');
  });

  it('fails when the table cannot be seen', () => {
    const c = readCheck('c.s.t', 'a@x.com', { error: 'TABLE_DOES_NOT_EXIST', missing: [] });
    expect(c.status).toBe('fail');
    expect(c.grants).toHaveLength(3);
  });
});

describe('holds', () => {
  const who = { userName: 'a@x.com', groups: ['analysts'] };
  it('counts group and ALL_PRIVILEGES grants', () => {
    expect(holds([{ principal: 'analysts', privileges: ['SELECT'] }], who, ['SELECT'])).toBe(true);
    expect(holds([{ principal: 'a@x.com', privileges: ['ALL_PRIVILEGES'] }], who, ['MODIFY'])).toBe(true);
    expect(holds([{ principal: 'others', privileges: ['SELECT'] }], who, ['SELECT'])).toBe(false);
  });
});

describe('fixCheck', () => {
  it('passes for the owner and warns when only MODIFY was found', () => {
    expect(fixCheck('c.s.t', 'a@x.com', { owner: true, modify: false }).status).toBe('pass');
    expect(fixCheck('c.s.t', 'a@x.com', { owner: false, modify: true }).status).toBe('warn');
    const none = fixCheck('c.s.t', 'a@x.com', null);
    expect(none.status).toBe('warn');
    expect(none.grants).toEqual(['GRANT MODIFY ON TABLE `c`.`s`.`t` TO `a@x.com`;']);
  });
});

describe('sandboxCheck', () => {
  it('explains a missing sandbox setting', () => {
    expect(sandboxCheck(null, 'a@x.com', false).status).toBe('fail');
    expect(sandboxCheck('c.s', 'a@x.com', true).status).toBe('pass');
    expect(sandboxCheck('c.s', 'a@x.com', false).grants).toHaveLength(3);
  });
});
