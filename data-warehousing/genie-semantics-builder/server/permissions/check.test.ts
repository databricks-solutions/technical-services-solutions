import { describe, expect, it } from 'vitest';
import { fixCheck, grant, sandboxCheck, selectCheck } from './check';

describe('grant', () => {
  it('quotes the securable and the principal', () => {
    expect(grant('SELECT', 'TABLE', 'c.s.t', 'a@x.com')).toBe('GRANT SELECT ON TABLE `c`.`s`.`t` TO `a@x.com`;');
  });
});

describe('selectCheck', () => {
  it('passes when the probe query ran', () => {
    expect(selectCheck('c.s.t', 'a@x.com', null)).toMatchObject({ status: 'pass', grants: [] });
  });

  it('names the missing privilege from the Unity Catalog error', () => {
    const c = selectCheck(
      'c.s.t',
      'a@x.com',
      "[INSUFFICIENT_PERMISSIONS] User does not have USE SCHEMA on Schema 'c.s'."
    );
    expect(c.status).toBe('fail');
    expect(c.grants).toEqual(['GRANT USE SCHEMA ON SCHEMA `c`.`s` TO `a@x.com`;']);
  });

  it('lists every grant when the error is not specific', () => {
    expect(selectCheck('c.s.t', 'a@x.com', 'TABLE_OR_VIEW_NOT_FOUND').grants).toHaveLength(3);
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
