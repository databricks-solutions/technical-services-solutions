import { describe, expect, it } from 'vitest';
import { fixCheck, grant, owns, readCheck, sandboxCheck } from './check';

describe('grant', () => {
  it('quotes the securable and the principal', () => {
    expect(grant('SELECT', 'TABLE', 'c.s.t', 'a@x.com')).toBe('GRANT SELECT ON TABLE `c`.`s`.`t` TO `a@x.com`;');
  });
});

describe('owns', () => {
  const who = { userName: 'a@x.com', groups: ['analysts'] };
  it('counts the user and the user groups', () => {
    expect(owns('a@x.com', who)).toBe(true);
    expect(owns('analysts', who)).toBe(true);
    expect(owns('others', who)).toBe(false);
    expect(owns(undefined, who)).toBe(false);
  });
});

describe('readCheck', () => {
  it('passes when the table loads as the user', () => {
    expect(readCheck('c.s.t', 'a@x.com', {})).toMatchObject({ status: 'pass', grants: [] });
  });

  it('fails with the read grants when the table cannot be seen', () => {
    const c = readCheck('c.s.t', 'a@x.com', { error: 'TABLE_DOES_NOT_EXIST' });
    expect(c.status).toBe('fail');
    expect(c.detail).toMatch(/TABLE_DOES_NOT_EXIST/);
    expect(c.grants).toEqual([
      'GRANT USE CATALOG ON CATALOG `c` TO `a@x.com`;',
      'GRANT USE SCHEMA ON SCHEMA `c`.`s` TO `a@x.com`;',
      'GRANT SELECT ON TABLE `c`.`s`.`t` TO `a@x.com`;',
    ]);
  });
});

describe('fixCheck', () => {
  it('passes for the owner', () => {
    expect(fixCheck('c.s.t', 'a@x.com', { owner: 'a@x.com', mine: true }).status).toBe('pass');
  });

  it('names the owner to ask, with the GRANT', () => {
    const c = fixCheck('c.s.t', 'a@x.com', { owner: 'data-eng', mine: false });
    expect(c.status).toBe('warn');
    expect(c.detail).toMatch(/data-eng/);
    expect(c.grants).toEqual(['GRANT MODIFY ON TABLE `c`.`s`.`t` TO `a@x.com`;']);
  });

  it('falls back to the table owner when the owner is not known', () => {
    expect(fixCheck('c.s.t', 'a@x.com', { mine: false }).detail).toMatch(/the table owner/);
  });
});

describe('sandboxCheck', () => {
  it('explains a missing sandbox setting', () => {
    expect(sandboxCheck(null, 'a@x.com', { mine: false }).status).toBe('fail');
  });

  it('passes for the owner and names the owner otherwise', () => {
    expect(sandboxCheck('c.s', 'a@x.com', { owner: 'a@x.com', mine: true }).status).toBe('pass');
    const c = sandboxCheck('c.s', 'a@x.com', { owner: 'platform', mine: false });
    expect(c.status).toBe('warn');
    expect(c.detail).toMatch(/platform/);
    expect(c.grants).toHaveLength(3);
  });
});
