import type { Application, Request } from 'express';
import { z } from 'zod';
import type { LakebasePool } from '@databricks/appkit';
import { CERT_TAG } from '../../shared/certify';
import type { CertificationView, CertSnapshot, CertTable, DataChecks } from '../../shared/certify';
import type { ReadinessCheck } from '../../shared/readiness';
import { requestReviewSchema } from '../../shared/review';
import { inaccessibleChecks, quoteId, quoteName, sqlString } from '../readiness/profile';
import type { TableProfile } from '../readiness/profile';
import { dataChecks, historyQuery, lastWrite, qualityQuery } from '../readiness/quality';
import { runStatement } from '../sql/runner';
import type { RunDeps } from '../sql/runner';
import type { UcDeps } from '../uc/metadata';
import { actorOf, handle, HttpError } from './http';
import { projectRepo } from './projects';
import { reviewRepo } from './review';

type Db = Pick<LakebasePool, 'query' | 'connect'>;
const idParam = z.object({ id: z.uuid() });
const applyBody = z.object({ statements: z.array(z.string().max(2000)).min(1).max(25) });

interface Row {
  id: string;
  full_name: string;
  data_checks: ReadinessCheck[] | null;
  data_checked_at: Date | null;
  data_checked_by: string | null;
  score: number | null;
  checks: ReadinessCheck[] | null;
  profile: TableProfile | null;
}

const dataOf = (r: Row): DataChecks | null =>
  r.data_checks && r.data_checked_at
    ? { checks: r.data_checks, checkedAt: r.data_checked_at.toISOString(), checkedBy: r.data_checked_by ?? '' }
    : null;

const VIEW_TYPES = new Set(['VIEW', 'METRIC_VIEW']);
export const certifyStatement = (fullName: string, tableType: string | undefined) =>
  `ALTER ${VIEW_TYPES.has(tableType ?? '') ? 'VIEW' : 'TABLE'} ${quoteName(fullName)} SET TAGS (${sqlString(CERT_TAG)} = 'certified')`;

/** The tag values now, read as the user from each catalog's information schema. */
export async function readStatus(tables: string[], actor: string, run: RunDeps): Promise<Map<string, string>> {
  const byCatalog = new Map<string, string[]>();
  for (const t of tables) {
    const [catalog, ...rest] = t.toLowerCase().split('.');
    byCatalog.set(catalog, [...(byCatalog.get(catalog) ?? []), rest.join('.')]);
  }
  const out = new Map<string, string>();
  for (const [catalog, names] of byCatalog) {
    const res = await runStatement(
      `SELECT schema_name, table_name, tag_value FROM ${quoteId(catalog)}.information_schema.table_tags
       WHERE tag_name = ${sqlString(CERT_TAG)} AND lower(concat_ws('.', schema_name, table_name)) IN (${names.map(sqlString).join(', ')})`,
      { actor, approved: false },
      run
    );
    for (const [schema, table, value] of res.rows) out.set(`${catalog}.${schema}.${table}`.toLowerCase(), value ?? '');
  }
  return out;
}

const sameTables = (a: string[], b: string[]) =>
  a.length === b.length && [...a].sort().join('|').toLowerCase() === [...b].sort().join('|').toLowerCase();

/**
 * Data certification: read-only data checks on the sources, a review by a named reviewer, then the governed tag,
 * set as the author with SQL that the author examines first. The app keeps the check results only.
 */
export function registerCertifyRoutes(
  app: Application,
  db: Db,
  runFor: (req: Request) => RunDeps,
  ucFor: (req: Request) => UcDeps
) {
  const projects = projectRepo(db);
  const reviews = reviewRepo(db);

  async function load(req: Request) {
    const actor = actorOf(req);
    const project = await projects.get(actor, idParam.parse(req.params).id);
    if (!project.parentId) throw new HttpError(400, 'Certification is on sub-projects.');
    const { rows } = await db.query<Row>(
      `SELECT s.id, s.full_name, s.data_checks, s.data_checked_at, s.data_checked_by, r.score, r.checks, r.profile
       FROM gsb.source s
       LEFT JOIN LATERAL (
         SELECT score, checks, profile FROM gsb.readiness_report WHERE source_id = s.id ORDER BY created_at DESC LIMIT 1
       ) r ON true
       WHERE s.project_id = $1 ORDER BY s.full_name`,
      [project.id]
    );
    return { actor, project, rows };
  }

  async function view(req: Request): Promise<CertificationView> {
    const { actor, project, rows } = await load(req);
    const run = runFor(req);
    let status = new Map<string, string>();
    let statusError: string | null = null;
    try {
      if (rows.length)
        status = await readStatus(
          rows.map((r) => r.full_name),
          actor,
          run
        );
    } catch (err) {
      statusError = `The certification tags could not be read: ${(err as Error).message.slice(0, 300)}`;
    }
    const latest = await reviews.latestData(project.id);
    const names = rows.map((r) => r.full_name);
    const changed =
      !!latest &&
      !sameTables(
        latest.snapshot.tables.map((t) => t.fullName),
        names
      );
    let statements: string[] = [];
    if (latest?.review.status === 'approved' && !changed) {
      const uc = ucFor(req);
      statements = await Promise.all(
        names.map(async (n) =>
          certifyStatement(
            n,
            await uc.table(n).then(
              (t) => t.table_type,
              () => undefined
            )
          )
        )
      );
    }
    const tables: CertTable[] = rows.map((r) => ({
      sourceId: r.id,
      fullName: r.full_name,
      readinessScore: r.score,
      data: dataOf(r),
      status: status.get(r.full_name.toLowerCase()) ?? null,
    }));
    return { tables, statusError, review: latest?.review ?? null, changed, statements };
  }

  app.get(
    '/api/projects/:id/certification',
    handle((req) => view(req))
  );

  /** One full scan and the history of each table, as the user. Only the check results are stored. */
  app.post(
    '/api/projects/:id/data-checks',
    handle(async (req) => {
      const { actor, project, rows } = await load(req);
      if (!rows.length) throw new HttpError(409, 'Add tables first.');
      if (rows.some((r) => !r.profile)) throw new HttpError(409, 'Assess the tables first.');
      const run = runFor(req);
      const ctx = { actor, projectId: project.id, approved: false };
      const results = await Promise.all(
        rows.map(async (r) => {
          const p = r.profile!;
          try {
            const counts = await runStatement(qualityQuery(p), ctx, run);
            const last = await runStatement(historyQuery(p), ctx, run).then(lastWrite, () => undefined);
            return { id: r.id, checks: dataChecks(p, counts, last) };
          } catch (err) {
            return { id: r.id, checks: inaccessibleChecks((err as Error).message) };
          }
        })
      );
      for (const r of results)
        await db.query(
          'UPDATE gsb.source SET data_checks = $2, data_checked_at = now(), data_checked_by = $3 WHERE id = $1',
          [r.id, JSON.stringify(r.checks), actor]
        );
      await db.query(
        `INSERT INTO gsb.audit_log (actor, action, project_id, outcome, detail) VALUES ($1, 'run_data_checks', $2, 'succeeded', $3)`,
        [
          actor,
          project.id,
          { tables: rows.length, failed: results.filter((r) => r.checks.some((c) => c.status === 'fail')).length },
        ]
      );
      return view(req);
    })
  );

  /** The reviewer sees the tables as they are now: the readiness, the data checks and the descriptions. */
  app.post(
    '/api/projects/:id/certification/reviews',
    handle(async (req) => {
      const body = requestReviewSchema.parse(req.body);
      const { actor, project, rows } = await load(req);
      if (!rows.length) throw new HttpError(409, 'Add tables first.');
      if (rows.some((r) => !r.profile || !r.data_checks))
        throw new HttpError(409, 'Run the data checks on each table before you ask for certification.');
      const snapshot: CertSnapshot = {
        tables: rows.map((r) => ({
          fullName: r.full_name,
          comment: r.profile!.comment,
          columns: r.profile!.columns,
          readinessScore: r.score,
          readiness: r.checks ?? [],
          data: dataOf(r)!,
        })),
      };
      await reviews.request(actor, project.id, body, { kind: 'data', snapshot });
      return view(req);
    })
  );

  app.post(
    '/api/projects/:id/certification/reviews/cancel',
    handle(async (req) => {
      const { actor, project } = await load(req);
      await reviews.cancel(actor, project.id, 'data');
      return view(req);
    })
  );

  /** Sets the tag as the author, only with the SQL the author examined, after an approval of the same tables. */
  app.post(
    '/api/projects/:id/certification/apply',
    handle(async (req) => {
      const { statements } = applyBody.parse(req.body);
      const { actor, project } = await load(req);
      const current = await view(req);
      if (current.review?.status !== 'approved')
        throw new HttpError(409, 'The tables need an approved certification review first.');
      if (current.changed) throw new HttpError(409, 'The tables changed since the review. Ask for a new review.');
      if (statements.join('\n') !== current.statements.join('\n'))
        throw new HttpError(409, 'The SQL changed since you examined it. Examine it again.');
      const run = runFor(req);
      for (const s of statements) await runStatement(s, { actor, projectId: project.id, approved: true }, run);
      return view(req);
    })
  );
}
