import type { AccessResult } from '../../shared/access';
import type { TestCase } from '../../shared/designer';
import { runStatement } from '../sql/runner';
import type { RunDeps } from '../sql/runner';
import { checkExpected, expectQuery, MAX_TEST_ROWS, measureQuery } from './validate';

/**
 * Runs each test on the promoted view as the signed-in person. A row filter shows as fewer rows, a column mask or a
 * missing grant as a failure. A test with an expected value returns its difference in percent, never the value.
 */
export async function runAccessCheck(
  target: string,
  tests: TestCase[],
  ctx: { actor: string; projectId: string },
  run: RunDeps
): Promise<AccessResult[]> {
  const out: AccessResult[] = [];
  for (const t of tests) {
    try {
      const res = await runStatement(
        t.expect ? expectQuery(target, t) : measureQuery(target, t),
        { ...ctx, approved: false },
        run
      );
      if (t.expect) out.push({ name: t.name, ...checkExpected(res.rows, t.expect) });
      else {
        const rows = Math.min(res.rows.length, MAX_TEST_ROWS);
        out.push({
          name: t.name,
          status: rows ? 'passed' : 'failed',
          rows,
          detail: rows ? `${rows}${res.rows.length > MAX_TEST_ROWS ? '+' : ''} rows.` : 'No rows.',
        });
      }
    } catch (err) {
      out.push({ name: t.name, status: 'error', rows: 0, detail: (err as Error).message.slice(0, 300) });
    }
  }
  return out;
}
