import { describe, expect, it, vi } from 'vitest';
import { runStatement } from './runner';
import type { AuditEntry, RunDeps } from './runner';
import { StatementRejected } from './allowlist';

function deps(overrides: Partial<RunDeps> = {}) {
  const audits: AuditEntry[] = [];
  const execute = vi.fn(() => Promise.resolve({ columns: ['x'], rows: [['1']] }));
  const d: RunDeps = {
    inUserContext: () => true,
    execute,
    audit: (e) => {
      audits.push(e);
      return Promise.resolve();
    },
    ...overrides,
  };
  return { d, audits, execute };
}

const DDL = "COMMENT ON TABLE sandbox.gsb.orders IS 'Orders'";
const ctx = { actor: 'user@example.com', projectId: 'p1' };

describe('runStatement', () => {
  it('runs read statements without an audit row', async () => {
    const { d, audits, execute } = deps();
    const result = await runStatement('SELECT 1;', { ...ctx, approved: false }, d);
    expect(result.rows).toEqual([['1']]);
    expect(execute).toHaveBeenCalledWith('SELECT 1');
    expect(audits).toEqual([]);
  });

  it('refuses DDL that was not approved and audits the rejection', async () => {
    const { d, audits, execute } = deps();
    await expect(runStatement(DDL, { ...ctx, approved: false }, d)).rejects.toThrow(StatementRejected);
    expect(execute).not.toHaveBeenCalled();
    expect(audits.map((a) => a.outcome)).toEqual(['rejected']);
  });

  it('audits approved DDL before and after it runs', async () => {
    const { d, audits } = deps();
    await runStatement(DDL, { ...ctx, approved: true }, d);
    expect(audits.map((a) => a.outcome)).toEqual(['approved', 'succeeded']);
    expect(audits[0]).toMatchObject({ actor: ctx.actor, projectId: 'p1', statement: DDL, action: 'execute_ddl' });
  });

  it('audits a failed DDL and rethrows', async () => {
    const { d, audits } = deps({ execute: () => Promise.reject(new Error('PERMISSION_DENIED')) });
    await expect(runStatement(DDL, { ...ctx, approved: true }, d)).rejects.toThrow('PERMISSION_DENIED');
    expect(audits.map((a) => a.outcome)).toEqual(['approved', 'failed']);
    expect(audits[1].detail).toEqual({ error: 'PERMISSION_DENIED' });
  });

  it('does not run DDL when the audit write fails', async () => {
    const { d, execute } = deps({ audit: () => Promise.reject(new Error('db down')) });
    await expect(runStatement(DDL, { ...ctx, approved: true }, d)).rejects.toThrow('db down');
    expect(execute).not.toHaveBeenCalled();
  });

  it('refuses to run outside a user (OBO) context', async () => {
    const { d, execute } = deps({ inUserContext: () => false });
    await expect(runStatement('SELECT 1', { ...ctx, approved: false }, d)).rejects.toThrow(/user context/);
    expect(execute).not.toHaveBeenCalled();
  });

  it('audits statements that fail the allowlist', async () => {
    const { d, audits } = deps();
    await expect(runStatement('DROP TABLE a.b.c', { ...ctx, approved: true }, d)).rejects.toThrow(StatementRejected);
    expect(audits).toMatchObject([{ outcome: 'rejected', statement: 'DROP TABLE a.b.c' }]);
  });
});
