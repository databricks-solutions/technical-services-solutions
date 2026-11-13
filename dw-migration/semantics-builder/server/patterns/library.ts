import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { parse } from 'yaml';
import { validateMetricView } from '../../shared/metricView';
import { expectedSchema, patternMetaSchema, VIEW_PLACEHOLDER } from '../../shared/patterns';
import type { Pattern } from '../../shared/patterns';
import { quoteName } from '../readiness/profile';
import { checkStatement } from '../sql/allowlist';

export const SLUG = /^[a-z][a-z0-9_]{0,40}$/;

export const testQueryFor = (pattern: Pick<Pattern, 'test'>, fullName: string) =>
  pattern.test.query.replaceAll(VIEW_PLACEHOLDER, quoteName(fullName));

async function loadOne(dir: string, slug: string): Promise<Pattern> {
  if (!SLUG.test(slug)) throw new Error('folder name must be lowercase letters, digits and _');
  const read = (file: string) => readFile(path.join(dir, slug, file), 'utf8');
  const meta = patternMetaSchema.parse(parse(await read('pattern.yml')));
  const yaml = await read('metric_view.yml');
  const errors = validateMetricView(yaml).issues.filter((i) => i.severity === 'error');
  if (errors.length) throw new Error(`metric_view.yml: line ${errors[0]?.line}: ${errors[0]?.message}`);
  checkStatement(testQueryFor(meta, 'sandbox.schema.view'));
  const expected = expectedSchema.parse(JSON.parse(await read('expected.json')));
  return { slug, ...meta, yaml, expected };
}

/** Loads every pattern folder. A folder that is not valid is skipped and reported, so one bad pattern cannot stop the app. */
export async function loadPatterns(dir: string): Promise<{ patterns: Pattern[]; skipped: string[] }> {
  const entries = (await readdir(dir, { withFileTypes: true })).filter((e) => e.isDirectory()).map((e) => e.name);
  const patterns: Pattern[] = [];
  const skipped: string[] = [];
  for (const slug of entries.sort()) {
    try {
      patterns.push(await loadOne(dir, slug));
    } catch (err) {
      skipped.push(`${slug}: ${(err as Error).message.split('\n')[0]}`);
    }
  }
  return { patterns, skipped };
}
