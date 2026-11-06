import type { Application, Request } from 'express';
import { z } from 'zod';
import type { LakebasePool } from '@databricks/appkit';
import { DICTIONARY_AGGREGATIONS, DICTIONARY_KINDS, DICTIONARY_STATUSES } from '../../shared/dictionary';
import type { DictionaryCoverage, DictionaryEntry, DictionaryPreview } from '../../shared/dictionary';
import type { TableProfile } from '../readiness/profile';
import { matchEntries } from '../dictionary/match';
import { loadDictionary } from '../dictionary/store';
import { MAX_CELL, MAX_ROWS, parseCsv, entriesFromTable, parseMarkdown, parseXlsx } from '../dictionary/parse';
import { sqlString } from '../readiness/profile';
import { runStatement } from '../sql/runner';
import type { RunDeps } from '../sql/runner';
import { certifySchema } from '../../shared/discover';
import { aggregationOf } from '../designer/import';
import { actorOf, handle, HttpError } from './http';
import { projectRepo } from './projects';

type Db = Pick<LakebasePool, 'query' | 'connect'>;

/** The app's JSON body limit is 1 MB; a base64 file of this size fits with room to spare. */
export const MAX_FILE_BYTES = 700 * 1024;

const cell = z.string().trim().max(MAX_CELL);
const entrySchema = z.strictObject({
  kind: z.enum(DICTIONARY_KINDS),
  name: cell.min(1),
  definition: cell.min(1),
  display_name: cell.optional(),
  formula: cell.optional(),
  aggregation: z.enum(DICTIONARY_AGGREGATIONS).optional(),
  format: cell.optional(),
  synonyms: z.array(cell.min(1)).max(10),
  grain: cell.optional(),
  source: cell.optional(),
  owner: cell.optional(),
  status: z.enum(DICTIONARY_STATUSES),
  notes: z.record(z.string().max(200), cell).refine((n) => Object.keys(n).length <= 50),
});
const fileName = z
  .string()
  .trim()
  .min(1)
  .max(255)
  .regex(/\.(xlsx|csv|md|markdown)$/i, 'Use an .xlsx, .csv or .md file.');
/** A file in a Unity Catalog volume. Plain path parts only, no "..". */
const VOLUME_PATH = /^\/Volumes\/[\w-]+\/[\w-]+\/[\w-]+(\/[\w .-]+)+\.(xlsx|csv|md|markdown)$/i;
const previewSchema = z.union([
  z.strictObject({ fileName, content: z.string().max(Math.ceil(MAX_FILE_BYTES / 3) * 4 + 8) }),
  z.strictObject({
    volumePath: z
      .string()
      .trim()
      .max(1000)
      .regex(VOLUME_PATH, 'Use a path like /Volumes/catalog/schema/volume/file.xlsx.')
      .refine((p) => !p.split('/').includes('..'), 'The path cannot contain "..".'),
  }),
]);
const importSchema = z.strictObject({
  fileName: z.union([fileName, z.string().regex(VOLUME_PATH)]),
  entries: z.array(entrySchema).max(MAX_ROWS),
});
const idParam = z.object({ id: z.uuid() });

const key = (e: Pick<DictionaryEntry, 'kind' | 'name'>) => `${e.kind}:${e.name.toLowerCase()}`;
const label = (e: Pick<DictionaryEntry, 'kind' | 'name'>) => `${e.name} (${e.kind})`;

export async function parseFile(name: string, buffer: Buffer) {
  if (buffer.length > MAX_FILE_BYTES) throw new HttpError(413, `The file is larger than ${MAX_FILE_BYTES / 1024} KB.`);
  if (/\.xlsx$/i.test(name)) {
    // An .xlsx file is a zip; anything else is not a workbook.
    if (buffer.subarray(0, 2).toString('latin1') !== 'PK') throw new HttpError(400, 'This is not an Excel workbook.');
    return parseXlsx(buffer);
  }
  const text = buffer.toString('utf8');
  if (/\.csv$/i.test(name)) return entriesFromTable(parseCsv(text), 'metric', name);
  return parseMarkdown(text);
}

/** The dictionary lives on the top-level project; a sub-project reads and writes its parent's. */
/** Reads a volume file as the user with the sql scope; the Files API would need another app scope. */
async function readVolumeFile(path: string, ctx: { actor: string; projectId: string }, run: RunDeps) {
  const res = await runStatement(
    `SELECT length, CASE WHEN length <= ${MAX_FILE_BYTES} THEN content END AS content
     FROM read_files(${sqlString(path)}, format => 'binaryFile')`,
    { ...ctx, approved: false },
    run
  );
  const [row] = res.rows;
  if (!row) throw new HttpError(404, 'No file at that path, or you cannot read it.');
  if (!row[1]) throw new HttpError(413, `The file is larger than ${MAX_FILE_BYTES / 1024} KB.`);
  return Buffer.from(row[1], 'base64');
}

export function registerDictionaryRoutes(app: Application, db: Db, runFor: (req: Request) => RunDeps) {
  const projects = projectRepo(db);

  async function owner(actor: string, id: string) {
    const p = await projects.get(actor, id);
    return p.parentId ? projects.get(actor, p.parentId) : p;
  }

  async function stored(projectId: string) {
    const { rows } = await db.query<{
      entry: DictionaryEntry;
      source_file: string;
      imported_by: string;
      imported_at: Date;
    }>(
      `SELECT entry, source_file, imported_by, imported_at FROM gsb.dictionary_entry
       WHERE project_id = $1 ORDER BY kind, lower(name)`,
      [projectId]
    );
    return rows;
  }

  app.get(
    '/api/projects/:id/dictionary',
    handle(async (req) => {
      const project = await owner(actorOf(req), idParam.parse(req.params).id);
      const rows = await stored(project.id);
      return {
        projectId: project.id,
        entries: rows.map((r) => r.entry),
        fileName: rows[0]?.source_file ?? null,
        importedBy: rows[0]?.imported_by ?? null,
        importedAt: rows[0]?.imported_at.toISOString() ?? null,
      };
    })
  );

  /** Parses the upload and compares it with the stored dictionary. Stores nothing. */
  app.post(
    '/api/projects/:id/dictionary/preview',
    handle(async (req): Promise<DictionaryPreview> => {
      const actor = actorOf(req);
      const project = await owner(actor, idParam.parse(req.params).id);
      const body = previewSchema.parse(req.body);
      const file =
        'volumePath' in body
          ? {
              name: body.volumePath,
              buffer: await readVolumeFile(body.volumePath, { actor, projectId: project.id }, runFor(req)).catch(
                (err: unknown) => {
                  if (err instanceof HttpError) throw err;
                  throw new HttpError(
                    400,
                    `The volume file could not be read: ${(err as Error).message.slice(0, 300)}`
                  );
                }
              ),
            }
          : { name: body.fileName, buffer: Buffer.from(body.content, 'base64') };
      const { entries, problems } = await parseFile(file.name, file.buffer).catch((err: unknown) => {
        if (err instanceof HttpError) throw err;
        throw new HttpError(400, `The file could not be read: ${(err as Error).message.slice(0, 200)}`);
      });
      const before = new Map((await stored(project.id)).map((r) => [key(r.entry), r.entry]));
      const after = new Map(entries.map((e) => [key(e), e]));
      return {
        fileName: file.name,
        entries,
        problems,
        added: entries.filter((e) => !before.has(key(e))).map(label),
        changed: entries
          .filter((e) => before.has(key(e)) && JSON.stringify(before.get(key(e))) !== JSON.stringify(e))
          .map(label),
        removed: [...before.values()].filter((e) => !after.has(key(e))).map(label),
      };
    })
  );

  /** Replaces the dictionary with the previewed entries, in one transaction. */
  app.post(
    '/api/projects/:id/dictionary/import',
    handle(async (req) => {
      const actor = actorOf(req);
      const project = await owner(actor, idParam.parse(req.params).id);
      const body = importSchema.parse(req.body);
      const keys = body.entries.map(key);
      if (new Set(keys).size !== keys.length) throw new HttpError(400, 'Two entries have the same kind and name.');
      const client = await db.connect();
      try {
        await client.query('BEGIN');
        await client.query('DELETE FROM gsb.dictionary_entry WHERE project_id = $1', [project.id]);
        for (const e of body.entries)
          await client.query(
            `INSERT INTO gsb.dictionary_entry (project_id, kind, name, entry, source_file, imported_by)
             VALUES ($1, $2, $3, $4, $5, $6)`,
            [project.id, e.kind, e.name, e, body.fileName, actor]
          );
        await client.query(
          `INSERT INTO gsb.audit_log (actor, action, project_id, outcome, detail)
           VALUES ($1, 'import_dictionary', $2, 'succeeded', $3)`,
          [actor, project.id, { fileName: body.fileName, entries: body.entries.length }]
        );
        await client.query('COMMIT');
      } catch (err) {
        await client.query('ROLLBACK');
        throw err;
      } finally {
        client.release();
      }
      return { imported: body.entries.length };
    })
  );

  app.post(
    '/api/projects/:id/dictionary/clear',
    handle(async (req) => {
      const actor = actorOf(req);
      const project = await owner(actor, idParam.parse(req.params).id);
      const { rowCount } = await db.query('DELETE FROM gsb.dictionary_entry WHERE project_id = $1', [project.id]);
      await db.query(
        `INSERT INTO gsb.audit_log (actor, action, project_id, outcome, detail)
         VALUES ($1, 'clear_dictionary', $2, 'succeeded', $3)`,
        [actor, project.id, { entries: rowCount }]
      );
      return { removed: rowCount };
    })
  );

  /** Adds or replaces one certified metric, from a definition that discover proposes. */
  app.post(
    '/api/projects/:id/dictionary/certify',
    handle(async (req) => {
      const actor = actorOf(req);
      const project = await owner(actor, idParam.parse(req.params).id);
      const body = certifySchema.parse(req.body);
      const entry: DictionaryEntry = {
        kind: 'metric',
        name: body.name,
        definition: `Canonical definition of ${body.name}, used by ${body.views} view${body.views === 1 ? '' : 's'}.`,
        formula: body.formula,
        aggregation: aggregationOf(body.formula),
        synonyms: [...new Set(body.synonyms.filter((n) => n.toLowerCase() !== body.name.toLowerCase()))],
        ...(body.source ? { source: body.source } : {}),
        status: 'certified',
        notes: {},
      };
      await db.query(
        `INSERT INTO gsb.dictionary_entry (project_id, kind, name, entry, source_file, imported_by)
         VALUES ($1, 'metric', $2, $3, 'discover', $4)
         ON CONFLICT (project_id, kind, lower(name))
         DO UPDATE SET entry = EXCLUDED.entry, source_file = 'discover', imported_by = EXCLUDED.imported_by,
           imported_at = now()`,
        [project.id, entry.name, entry, actor]
      );
      await db.query(
        `INSERT INTO gsb.audit_log (actor, action, project_id, target, outcome, detail)
         VALUES ($1, 'certify_dictionary_entry', $2, $3, 'succeeded', $4)`,
        [actor, project.id, entry.name, { formula: entry.formula }]
      );
      return { entry };
    })
  );

  /** Rule-based coverage from the last assessment of each source. Empty when nothing is assessed. */
  app.get(
    '/api/projects/:id/dictionary/coverage',
    handle(async (req): Promise<DictionaryCoverage> => {
      const project = await projects.get(actorOf(req), idParam.parse(req.params).id);
      const entries = (await loadDictionary(db, project.id)).filter((e) => e.kind !== 'term');
      const { rows } = await db.query<{ profile: TableProfile }>(
        `SELECT DISTINCT ON (r.source_id) r.profile FROM gsb.readiness_report r
         JOIN gsb.source s ON s.id = r.source_id
         WHERE r.project_id = $1 AND r.profile IS NOT NULL ORDER BY r.source_id, r.created_at DESC`,
        [project.id]
      );
      const { matched, unmatched } = matchEntries(
        entries,
        rows.map((r) => r.profile)
      );
      return {
        total: entries.length,
        matched: matched.map((m) => ({
          name: m.entry.name,
          kind: m.entry.kind,
          status: m.entry.status,
          via: m.via,
          columns: m.columns.map((c) => `${c.table.split('.').pop()}.${c.column}`),
        })),
        missing: unmatched.map((e) => ({ name: e.name, kind: e.kind, status: e.status })),
      };
    })
  );
}
