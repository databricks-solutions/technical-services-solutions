// Dev tool: runs each pattern on a warehouse and writes its expected.json from the real result.
// Usage: pnpm tsx scripts/run-patterns.ts --profile <PROFILE> --warehouse <ID> --sandbox <catalog.schema> [slug ...]
import { execFile } from 'node:child_process';
import { readdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { parseArgs, promisify } from 'node:util';
import { parse } from 'yaml';
import { patternMetaSchema } from '../shared/patterns';
import { createStatement, dropStatement } from '../server/designer/validate';
import { testQueryFor } from '../server/patterns/library';

const { values, positionals } = parseArgs({
  options: { profile: { type: 'string' }, warehouse: { type: 'string' }, sandbox: { type: 'string' } },
  allowPositionals: true,
});
if (!values.profile || !values.warehouse || !values.sandbox?.includes('.'))
  throw new Error('Pass --profile, --warehouse and --sandbox <catalog.schema>');
const { profile, warehouse, sandbox } = values;

interface StatementResponse {
  status: { state: string; error?: { message?: string } };
  manifest?: { schema?: { columns?: { name: string }[] } };
  result?: { data_array?: (string | null)[][] };
}

async function sql(statement: string) {
  const body = JSON.stringify({ warehouse_id: warehouse, statement, wait_timeout: '50s', format: 'JSON_ARRAY' });
  const { stdout } = await promisify(execFile)(
    'databricks',
    ['api', 'post', '/api/2.0/sql/statements', '--json', body, '--profile', profile, '-o', 'json'],
    { maxBuffer: 64 * 1024 * 1024 }
  );
  const res = JSON.parse(stdout) as StatementResponse;
  if (res.status.state !== 'SUCCEEDED') throw new Error(res.status.error?.message ?? res.status.state);
  return { columns: res.manifest?.schema?.columns?.map((c) => c.name) ?? [], rows: res.result?.data_array ?? [] };
}

const dir = path.resolve('patterns');
const slugs = positionals.length
  ? positionals
  : (await readdir(dir, { withFileTypes: true })).filter((e) => e.isDirectory()).map((e) => e.name);
let failed = 0;
for (const slug of slugs.sort()) {
  const view = `${sandbox}.${slug}__gsb_00000000`;
  try {
    const meta = patternMetaSchema.parse(parse(await readFile(path.join(dir, slug, 'pattern.yml'), 'utf8')));
    await sql(createStatement(view, await readFile(path.join(dir, slug, 'metric_view.yml'), 'utf8')));
    const { columns, rows } = await sql(testQueryFor(meta, view));
    if (rows.length > 50) throw new Error(`the test query returned ${rows.length} rows; keep it to 50 or fewer`);
    await writeFile(path.join(dir, slug, 'expected.json'), `${JSON.stringify({ columns, rows }, null, 2)}\n`);
    console.log(`ok   ${slug}: ${rows.length} rows`);
  } catch (err) {
    failed++;
    console.log(`FAIL ${slug}: ${(err as Error).message.split('\n')[0]}`);
  } finally {
    await sql(dropStatement(view)).catch(() => undefined);
  }
}
process.exitCode = failed ? 1 : 0;
