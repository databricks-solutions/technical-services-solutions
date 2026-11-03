import { getExecutionContext, getWarehouseId, isInUserContext } from '@databricks/appkit';
import { checkStatement, StatementRejected } from './allowlist';

export interface StatementResult {
  columns: string[];
  rows: (string | null)[][];
}

export interface AuditEntry {
  actor: string;
  action: string;
  projectId?: string;
  statement: string;
  outcome: 'approved' | 'rejected' | 'succeeded' | 'failed';
  detail?: Record<string, unknown>;
}

export interface RunDeps {
  inUserContext(): boolean;
  execute(statement: string): Promise<StatementResult>;
  audit(entry: AuditEntry): Promise<void>;
}

export interface RunContext {
  actor: string;
  projectId?: string;
  /** True only when a human approved this exact statement in the UI. */
  approved: boolean;
}

const AUDIT_STATEMENT_MAX = 10_000;

/** The only path to the warehouse: allowlist, approval gate for DDL, audit before and after. */
export async function runStatement(sql: string, ctx: RunContext, deps: RunDeps): Promise<StatementResult> {
  if (!deps.inUserContext()) throw new Error('Statements must run in a user context (OBO), never as the app');
  const base = { actor: ctx.actor, action: 'execute_ddl', projectId: ctx.projectId };

  let checked;
  try {
    checked = checkStatement(sql);
    if (checked.kind === 'ddl' && !ctx.approved) throw new StatementRejected('DDL needs human approval');
  } catch (err) {
    await deps.audit({
      ...base,
      statement: sql.slice(0, AUDIT_STATEMENT_MAX),
      outcome: 'rejected',
      detail: { error: (err as Error).message },
    });
    throw err;
  }

  if (checked.kind === 'read') return deps.execute(checked.statement);

  const entry = { ...base, statement: checked.statement };
  await deps.audit({ ...entry, outcome: 'approved' });
  try {
    const result = await deps.execute(checked.statement);
    await deps.audit({ ...entry, outcome: 'succeeded' });
    return result;
  } catch (err) {
    await deps.audit({ ...entry, outcome: 'failed', detail: { error: (err as Error).message } });
    throw err;
  }
}

interface QueryablePool {
  query(sql: string, params: unknown[]): Promise<unknown>;
}

/** Production wiring: execute on the warehouse as the calling user, audit to Lakebase as the app. */
export function warehouseDeps(pool: QueryablePool): RunDeps {
  return {
    inUserContext: isInUserContext,
    async execute(statement) {
      const res = await getExecutionContext().client.statementExecution.executeStatement({
        warehouse_id: await getWarehouseId(),
        statement,
        wait_timeout: '50s',
        on_wait_timeout: 'CANCEL',
        row_limit: 1000,
      });
      if (res.status?.state !== 'SUCCEEDED') {
        throw new Error(res.status?.error?.message ?? `Statement ended in state ${res.status?.state ?? 'unknown'}`);
      }
      return {
        columns: res.manifest?.schema?.columns?.map((c) => c.name ?? '') ?? [],
        rows: res.result?.data_array ?? [],
      };
    },
    async audit(e) {
      await pool.query(
        'INSERT INTO gsb.audit_log (actor, action, project_id, target, statement, outcome, detail) VALUES ($1, $2, $3, NULL, $4, $5, $6)',
        [e.actor, e.action, e.projectId ?? null, e.statement, e.outcome, e.detail ?? null]
      );
    },
  };
}
