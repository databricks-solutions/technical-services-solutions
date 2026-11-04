import type { Application, Request } from 'express';
import { z } from 'zod';
import type { LakebasePool } from '@databricks/appkit';
import { UC_TABLE_NAME } from '../../shared/brief';
import type { SemanticBrief } from '../../shared/brief';
import type {
  Assessment,
  ReadinessCheck,
  ReadinessView,
  Recommendation,
  RecommendationStatus,
  Link,
  PermissionCheck,
  RelatedTable,
  RelationCheck,
} from '../../shared/readiness';
import { callTool } from '../llm/llm';
import type { LlmDeps } from '../llm/llm';
import { assessSourcePrompt, assessSourceRequest } from '../llm/prompts/readiness';
import { relatePrompt, relateRequest } from '../llm/prompts/relate';
import { buildRecommendations, checksFor, inaccessibleChecks } from '../readiness/profile';
import { sandboxSchema } from '../designer/validate';
import { fixCheck, owns, readCheck, sandboxCheck } from '../permissions/check';
import { profileFromTable } from '../uc/metadata';
import type { UcDeps } from '../uc/metadata';
import { applyEffect, inferLinks, projectScore, tableAreas, tableScore } from '../readiness/score';
import type { FixEffect } from '../readiness/score';
import type { NewRecommendation, TableProfile } from '../readiness/profile';
import { runStatement } from '../sql/runner';
import type { RunDeps } from '../sql/runner';
import { projectRepo } from './projects';
import { actorOf, handle, HttpError } from './http';

type Db = Pick<LakebasePool, 'query' | 'connect'>;

interface SourceRow {
  id: string;
  full_name: string;
  role: Assessment['role'];
  report_id: string | null;
  score: number | null;
  checks: ReadinessCheck[] | null;
  assessment: Assessment | null;
  profile: TableProfile | null;
  created_at: Date | null;
}

interface RecRow {
  id: string;
  full_name: string | null;
  kind: Recommendation['kind'];
  title: string;
  rationale: string | null;
  statements: string[];
  status: RecommendationStatus;
  error: string | null;
  decided_by: string | null;
  decided_at: Date | null;
  effect: FixEffect | null;
}

export interface SourceResult {
  sourceId: string;
  role: Assessment['role'];
  checks: ReadinessCheck[];
  assessment: Assessment | null;
  profile: TableProfile | null;
  score: number | null;
  model: string | null;
  recommendations: NewRecommendation[];
}

export const MAX_SOURCES = 25;

// Stored briefs are typed but not re-validated, so older rows may lack a list.
const briefItems = (brief: SemanticBrief | null) =>
  [...(brief?.measures ?? []), ...(brief?.dimensions ?? [])].map((x) => x.name);
const isOpen = (status: RecommendationStatus) => status === 'proposed' || status === 'failed';

/**
 * Scores come from the stored table metadata, not the warehouse. Applied fixes are folded into
 * that metadata, so the score moves as soon as a fix runs, before the next assessment.
 */
export function buildView(
  sources: SourceRow[],
  recs: RecRow[],
  confirmed: { brief: SemanticBrief; version: number } | null
): ReadinessView {
  const brief = confirmed?.brief ?? null;
  const applied = recs.filter((r) => r.status === 'applied' && r.effect && r.full_name);
  const profiles = new Map<string, TableProfile>();
  for (const s of sources) {
    if (!s.profile) continue;
    profiles.set(
      s.full_name,
      applied.filter((r) => r.full_name === s.full_name).reduce((p, r) => applyEffect(p, r.effect!), s.profile)
    );
  }
  const all = [...profiles.values()];

  const items = briefItems(brief);
  const coveredItems = new Set(sources.flatMap((s) => (s.assessment?.coverage ?? []).map((c) => c.item)));
  const missing = items.filter((i) => !coveredItems.has(i));
  const stale = sources.some((s) => s.assessment && s.assessment.briefVersion !== confirmed?.version);
  const coverage = confirmed ? { covered: items.length - missing.length, total: items.length, missing, stale } : null;
  const base = all.length ? projectScore(all, coverage) : null;

  const gain = (r: RecRow) => {
    const p = r.full_name ? profiles.get(r.full_name) : undefined;
    if (!base || !p || !r.effect || !isOpen(r.status)) return 0;
    const next = all.map((x) => (x === p ? applyEffect(p, r.effect!) : x));
    return projectScore(next, coverage).score - base.score;
  };

  const inProject = new Set(all.map((p) => p.fullName));
  const declared = all.flatMap((p) =>
    p.foreignKeys
      .filter((f) => inProject.has(f.references))
      .map((f) => ({
        from: p.fullName,
        column: f.columns.join(', '),
        to: f.references,
        refColumn: f.refColumns.join(', '),
        declared: true,
      }))
  );
  const declaredCols = new Set(
    all.flatMap((p) => p.foreignKeys.flatMap((f) => f.columns.map((c) => `${p.fullName}.${c}`.toLowerCase())))
  );
  const links = [
    ...declared,
    ...inferLinks(all)
      .filter((l) => !declaredCols.has(`${l.from}.${l.column}`.toLowerCase()))
      .map((l) => ({ ...l, declared: false })),
  ];
  const linked = new Set(links.flatMap((l) => [l.from, l.to]));

  return {
    score: base,
    ontology: {
      entities: sources.map((s) => {
        const p = profiles.get(s.full_name);
        return {
          table: s.full_name,
          entity: s.assessment?.entity || s.full_name.split('.').pop()!,
          role: s.role,
          score: p ? tableScore(tableAreas(p, all)) : s.score,
        };
      }),
      links,
      unmapped: missing,
      unlinked: all.length > 1 ? all.map((p) => p.fullName).filter((t) => !linked.has(t)) : [],
    },
    sources: sources.map((r) => {
      const p = profiles.get(r.full_name);
      const areas = p ? tableAreas(p, all) : [];
      return {
        sourceId: r.id,
        fullName: r.full_name,
        role: r.role,
        report: r.report_id
          ? {
              id: r.report_id,
              score: p ? tableScore(areas) : r.score,
              areas,
              checks: r.checks ?? [],
              assessment: r.assessment,
              createdAt: r.created_at!.toISOString(),
            }
          : null,
      };
    }),
    recommendations: recs.map((r) => ({
      id: r.id,
      sourceName: r.full_name,
      kind: r.kind,
      title: r.title,
      rationale: r.rationale ?? '',
      statements: r.statements,
      status: r.status,
      error: r.error,
      decidedBy: r.decided_by,
      decidedAt: r.decided_at?.toISOString() ?? null,
      scoreGain: gain(r),
    })),
  };
}

export function readinessRepo(db: Db) {
  return {
    async view(projectId: string): Promise<ReadinessView> {
      const [sources, recs, brief] = await Promise.all([
        db.query<SourceRow>(
          `SELECT s.id, s.full_name, s.role, r.id AS report_id, r.score, r.checks, r.assessment, r.profile, r.created_at
           FROM gsb.source s
           LEFT JOIN LATERAL (
             SELECT * FROM gsb.readiness_report WHERE source_id = s.id ORDER BY created_at DESC LIMIT 1
           ) r ON true
           WHERE s.project_id = $1 ORDER BY s.full_name`,
          [projectId]
        ),
        db.query<RecRow>(
          `SELECT r.id, s.full_name, r.kind, r.title, r.rationale, r.statements, r.status, r.error, r.decided_by, r.decided_at, r.effect
           FROM gsb.recommendation r LEFT JOIN gsb.source s ON s.id = r.source_id
           WHERE r.project_id = $1
           ORDER BY array_position(ARRAY['table_comment', 'column_comments', 'primary_key', 'foreign_key'], r.kind),
                    s.full_name, r.created_at`,
          [projectId]
        ),
        db.query<{ brief: SemanticBrief; version: number }>(
          `SELECT content->'brief' AS brief, version FROM gsb.semantic_brief WHERE project_id = $1 AND status = 'confirmed'
           ORDER BY version DESC LIMIT 1`,
          [projectId]
        ),
      ]);
      return buildView(sources.rows, recs.rows, brief.rows[0] ?? null);
    },

    /** Replaces open fixes with the new assessment. Applied and rejected fixes stay as history. */
    async saveAssessment(actor: string, projectId: string, results: SourceResult[]): Promise<void> {
      const client = await db.connect();
      try {
        await client.query('BEGIN');
        await client.query(
          `DELETE FROM gsb.recommendation WHERE project_id = $1 AND status IN ('proposed', 'failed')`,
          [projectId]
        );
        let count = 0;
        for (const r of results) {
          const { rows } = await client.query<{ id: string }>(
            `INSERT INTO gsb.readiness_report (project_id, source_id, score, checks, assessment, profile, model, created_by)
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id`,
            [projectId, r.sourceId, r.score, JSON.stringify(r.checks), r.assessment, r.profile, r.model, actor]
          );
          await client.query('UPDATE gsb.source SET role = $2 WHERE id = $1', [r.sourceId, r.role]);
          for (const rec of r.recommendations) {
            await client.query(
              `INSERT INTO gsb.recommendation (project_id, readiness_report_id, source_id, kind, title, rationale, statements, effect)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)`,
              [projectId, rows[0].id, r.sourceId, rec.kind, rec.title, rec.rationale, rec.statements, rec.effect]
            );
            count++;
          }
        }
        await client.query(
          `INSERT INTO gsb.audit_log (actor, action, project_id, outcome, detail) VALUES ($1, 'assess_sources', $2, 'succeeded', $3)`,
          [actor, projectId, { sources: results.length, recommendations: count }]
        );
        await client.query('COMMIT');
      } catch (err) {
        await client.query('ROLLBACK');
        throw err;
      } finally {
        client.release();
      }
    },

    /**
     * Moves an open fix to approved only if the statements match what the user saw.
     * The status check makes a double click or a second tab a no-op.
     */
    async claim(actor: string, projectId: string, id: string, statements: string[]): Promise<void> {
      const { rows } = await db.query(
        `UPDATE gsb.recommendation SET status = 'approved', decided_by = $3, decided_at = now(), error = NULL
         WHERE id = $1 AND project_id = $2 AND status IN ('proposed', 'failed') AND statements = $4::text[]
         RETURNING id`,
        [id, projectId, actor, statements]
      );
      if (!rows[0]) throw new HttpError(409, 'This fix changed or was already handled. Reload the page.');
    },

    async finish(id: string, status: 'applied' | 'failed', error: string | null): Promise<void> {
      await db.query(
        `UPDATE gsb.recommendation SET status = $2, error = $3, applied_at = CASE WHEN $2 = 'applied' THEN now() END
         WHERE id = $1`,
        [id, status, error]
      );
    },

    async reject(actor: string, projectId: string, id: string): Promise<void> {
      const { rows } = await db.query(
        `UPDATE gsb.recommendation SET status = 'rejected', decided_by = $3, decided_at = now()
         WHERE id = $1 AND project_id = $2 AND status IN ('proposed', 'failed') RETURNING id`,
        [id, projectId, actor]
      );
      if (!rows[0]) throw new HttpError(409, 'This fix changed or was already handled. Reload the page.');
      await db.query(
        `INSERT INTO gsb.audit_log (actor, action, project_id, target, outcome) VALUES ($1, 'reject_recommendation', $2, $3, 'succeeded')`,
        [actor, projectId, id]
      );
    },
  };
}

/** Profiles each source from the Unity Catalog API, as the user. A table the user cannot read returns its error. */
export function describeSources<S extends { fullName: string }>(
  sources: S[],
  uc: UcDeps
): Promise<{ source: S; profile?: TableProfile; error?: string }[]> {
  return Promise.all(
    sources.map(async (source) => {
      try {
        return { source, profile: profileFromTable(source.fullName, await uc.table(source.fullName)) };
      } catch (err) {
        return { source, error: (err as Error).message };
      }
    })
  );
}

/** Keeps only pairs whose brief item and column both exist, with their canonical names. */
function validCoverage(pairs: { item: string; column: string }[], p: TableProfile, items: string[]) {
  const item = new Map(items.map((i) => [i.toLowerCase(), i]));
  const col = new Map(p.columns.map((c) => [c.name.toLowerCase(), c.name]));
  return pairs.flatMap(({ item: i, column: c }) => {
    const name = item.get(i.trim().toLowerCase());
    const column = col.get(c.trim().toLowerCase());
    return name && column ? [{ item: name, column }] : [];
  });
}

/** Columns of every table in the schemas of the given tables, from the Unity Catalog API as the user. */
async function schemaColumns(tables: string[], uc: UcDeps) {
  const schemas = [...new Set(tables.map((t) => t.split('.').slice(0, 2).join('.')))].slice(0, MAX_RELATED_SCHEMAS);
  const out = new Map<string, { name: string; type: string; comment: string }[]>();
  const lists = await Promise.all(
    schemas.map(async (schema) => {
      const [catalog, name] = schema.split('.');
      return { schema, tables: await uc.tables(catalog, name, true) };
    })
  );
  for (const { schema, tables: list } of lists)
    for (const t of list)
      out.set(
        `${schema}.${t.name ?? ''}`,
        (t.columns ?? []).map((c) => ({ name: c.name ?? '', type: (c.type_text ?? '').toLowerCase(), comment: '' }))
      );
  return out;
}

/** Tables connected by joins, largest group first. */
export function joinGroups(tables: string[], links: Link[]): string[][] {
  const parent = new Map(tables.map((t) => [t, t]));
  const find = (t: string): string => (parent.get(t) === t ? t : find(parent.get(t)!));
  for (const l of links) if (parent.has(l.from) && parent.has(l.to)) parent.set(find(l.from), find(l.to));
  const groups = new Map<string, string[]>();
  for (const t of tables) groups.set(find(t), [...(groups.get(find(t)) ?? []), t]);
  return [...groups.values()].sort((a, b) => b.length - a.length);
}

const idParam = z.object({ id: z.uuid() });
const recParam = idParam.extend({ recId: z.uuid() });
const sourceParam = idParam.extend({ sourceId: z.uuid() });
const checkBody = z.object({ tables: z.array(z.string().trim().regex(UC_TABLE_NAME)).min(1).max(MAX_SOURCES) });
const addBody = z.object({ tables: z.array(z.string().trim().regex(UC_TABLE_NAME)).min(1).max(MAX_SOURCES) });
const MAX_RELATED_SCHEMAS = 5;
const short = (t: string) => t.split('.').pop()!;

const applyBody = z.object({ statements: z.array(z.string().min(1).max(200_000)).min(1).max(200) });

export function registerReadinessRoutes(
  app: Application,
  db: Db,
  llmFor: (req: Request) => LlmDeps,
  runFor: (req: Request) => RunDeps,
  ucFor: (req: Request) => UcDeps
) {
  const projects = projectRepo(db);
  const repo = readinessRepo(db);

  app.get(
    '/api/projects/:id/readiness',
    handle(async (req) => {
      const project = await projects.get(actorOf(req), idParam.parse(req.params).id);
      return repo.view(project.id);
    })
  );

  app.post(
    '/api/projects/:id/readiness/run',
    handle(async (req) => {
      const actor = actorOf(req);
      const project = await projects.get(actor, idParam.parse(req.params).id);
      const latest = await projects.latestBrief(project.id);
      const brief = latest?.status === 'confirmed' ? latest : null;
      const { sources } = await repo.view(project.id);
      if (!sources.length) throw new HttpError(409, 'Add the tables to model first.');
      if (sources.length > MAX_SOURCES) throw new HttpError(400, `Assess at most ${MAX_SOURCES} sources at a time.`);

      const described = await describeSources(sources, ucFor(req));
      const profiles = described.flatMap((d) => (d.profile ? [d.profile] : []));

      const items = briefItems(brief?.brief ?? null);
      const llm = llmFor(req);
      const results = await Promise.all(
        described.map(async ({ source, profile, error }): Promise<SourceResult> => {
          if (!profile) {
            return {
              sourceId: source.sourceId,
              role: source.role,
              checks: inaccessibleChecks(error ?? ''),
              assessment: null,
              profile: null,
              score: null,
              model: null,
              recommendations: [],
            };
          }
          const checks = checksFor(profile);
          const others = profiles.filter((p) => p !== profile);
          const out = await callTool(
            assessSourcePrompt,
            assessSourceRequest(brief?.brief ?? null, profile, checks, others),
            llm
          );
          const byName = new Map<string, TableProfile>(others.map((o) => [o.fullName.toLowerCase(), o]));
          return {
            sourceId: source.sourceId,
            role: out.role,
            checks,
            assessment: {
              role: out.role,
              entity: out.entity,
              coverage: validCoverage(out.coverage, profile, items),
              briefVersion: brief?.version ?? null,
              score: out.score,
              summary: out.summary,
              findings: out.findings,
            },
            profile,
            score: tableScore(tableAreas(profile, profiles)),
            model: llm.endpoint ?? null,
            recommendations: buildRecommendations(profile, out, byName),
          };
        })
      );
      await repo.saveAssessment(actor, project.id, results);
      return repo.view(project.id);
    })
  );

  app.post(
    '/api/projects/:id/recommendations/:recId/apply',
    handle(async (req) => {
      const actor = actorOf(req);
      const { id, recId } = recParam.parse(req.params);
      const project = await projects.get(actor, id);
      const { statements } = applyBody.parse(req.body);
      await repo.claim(actor, project.id, recId, statements);

      const run = runFor(req);
      for (const [i, statement] of statements.entries()) {
        try {
          await runStatement(statement, { actor, projectId: project.id, approved: true }, run);
        } catch (err) {
          const reason = (err as Error).message.slice(0, 500);
          await repo.finish(recId, 'failed', `Statement ${i + 1} of ${statements.length} failed: ${reason}`);
          return repo.view(project.id);
        }
      }
      await repo.finish(recId, 'applied', null);
      return repo.view(project.id);
    })
  );

  app.post(
    '/api/projects/:id/recommendations/:recId/reject',
    handle(async (req) => {
      const actor = actorOf(req);
      const { id, recId } = recParam.parse(req.params);
      const project = await projects.get(actor, id);
      await repo.reject(actor, project.id, recId);
      return repo.view(project.id);
    })
  );

  app.post(
    '/api/projects/:id/sources',
    handle(async (req) => {
      const actor = actorOf(req);
      const project = await projects.get(actor, idParam.parse(req.params).id);
      const { tables } = addBody.parse(req.body);
      const { sources } = await repo.view(project.id);
      const have = new Set(sources.map((x) => x.fullName.toLowerCase()));
      const fresh = [...new Set(tables)].filter((t) => !have.has(t.toLowerCase()));
      if (have.size + fresh.length > MAX_SOURCES)
        throw new HttpError(400, `A sub-project holds at most ${MAX_SOURCES} sources.`);
      if (fresh.length)
        await db.query(
          `WITH ins AS (
             INSERT INTO gsb.source (project_id, full_name, added_by) SELECT $1, unnest($2::text[]), $3
             ON CONFLICT (project_id, full_name) DO NOTHING RETURNING full_name
           )
           INSERT INTO gsb.audit_log (actor, action, project_id, outcome, detail)
           SELECT $3, 'add_sources', $1, 'succeeded', jsonb_build_object('tables', array_agg(full_name)) FROM ins`,
          [project.id, fresh, actor]
        );
      return repo.view(project.id);
    })
  );

  app.post(
    '/api/projects/:id/sources/:sourceId/remove',
    handle(async (req) => {
      const actor = actorOf(req);
      const { id, sourceId } = sourceParam.parse(req.params);
      const project = await projects.get(actor, id);
      const { rows } = await db.query<{ full_name: string }>(
        `WITH del AS (DELETE FROM gsb.source WHERE id = $1 AND project_id = $2 RETURNING full_name)
         INSERT INTO gsb.audit_log (actor, action, project_id, target, outcome)
         SELECT $3, 'remove_source', $2, full_name, 'succeeded' FROM del RETURNING target AS full_name`,
        [sourceId, project.id, actor]
      );
      if (!rows[0]) throw new HttpError(404, 'Source not found.');
      return repo.view(project.id);
    })
  );

  /**
   * Tables in the same schemas that join to the sources: declared foreign keys from the last
   * assessment, and key-name matches from the Unity Catalog API, read as the user.
   */
  app.get(
    '/api/projects/:id/sources/related',
    handle(async (req): Promise<RelatedTable[]> => {
      const actor = actorOf(req);
      const project = await projects.get(actor, idParam.parse(req.params).id);
      const { sources } = await repo.view(project.id);
      const mine = new Set(sources.map((s) => s.fullName.toLowerCase()));
      const reasons = new Map<string, Set<string>>();
      const add = (table: string, why: string) => {
        if (mine.has(table.toLowerCase())) return;
        reasons.set(table, (reasons.get(table) ?? new Set()).add(why));
      };

      const { rows: profiles } = await db.query<{ profile: TableProfile }>(
        `SELECT DISTINCT ON (source_id) profile FROM gsb.readiness_report
         WHERE project_id = $1 AND profile IS NOT NULL ORDER BY source_id, created_at DESC`,
        [project.id]
      );
      for (const { profile } of profiles)
        for (const f of profile.foreignKeys)
          add(f.references, `${short(profile.fullName)} declares a foreign key to it`);

      const tables = await schemaColumns(
        sources.map((s) => s.fullName),
        ucFor(req)
      );
      const isMine = (t: string) => mine.has(t.toLowerCase());
      for (const l of inferLinks([...tables].map(([fullName, columns]) => ({ fullName, columns })))) {
        if (isMine(l.from) && !isMine(l.to))
          add(l.to, `${short(l.from)}.${l.column} matches ${short(l.to)}.${l.refColumn}`);
        if (isMine(l.to) && !isMine(l.from)) add(l.from, `${short(l.from)}.${l.column} references ${short(l.to)}`);
      }
      return [...reasons]
        .map(([table, why]) => ({ table, reasons: [...why] }))
        .sort((a, b) => b.reasons.length - a.reasons.length || a.table.localeCompare(b.table));
    })
  );

  /**
   * What the user needs, from the Unity Catalog and SQL warehouse APIs as the user. No warehouse
   * query runs. Effective permissions include inherited and group grants.
   */
  app.get(
    '/api/projects/:id/permissions',
    handle(async (req): Promise<PermissionCheck[]> => {
      const actor = actorOf(req);
      const project = await projects.get(actor, idParam.parse(req.params).id);
      const { sources } = await repo.view(project.id);
      const uc = ucFor(req);
      const sandbox = sandboxSchema();
      const warehouse = {
        id: 'warehouse',
        group: 'warehouse' as const,
        label: 'Run queries on the SQL warehouse',
      };
      try {
        await uc.warehouse();
      } catch (err) {
        const code = /\b([A-Z][A-Z_]{4,})\b/.exec((err as Error).message)?.[1];
        return [
          {
            ...warehouse,
            status: 'fail',
            detail: `You cannot use the SQL warehouse of the app${code ? ` (${code})` : ''}. Ask a workspace admin for CAN USE on it.`,
            grants: [],
          },
        ];
      }
      const who = await uc.me();
      const ownership = (owner: string | undefined) => ({ owner, mine: owns(owner, who) });
      const checks: PermissionCheck[] = [
        { ...warehouse, status: 'pass', detail: 'You can use the SQL warehouse of the app.', grants: [] },
      ];
      if (sandbox) {
        const [schemaOwner, catalogOwner] = await Promise.all([
          uc.owner('schema', sandbox).catch(() => undefined),
          uc.owner('catalog', sandbox.split('.')[0]).catch(() => undefined),
        ]);
        const o = owns(catalogOwner, who) ? ownership(catalogOwner) : ownership(schemaOwner);
        checks.push(sandboxCheck(sandbox, actor, o));
      } else checks.push(sandboxCheck(null, actor, { mine: false }));

      const results = await Promise.all(
        sources.map(async ({ fullName: t }) => {
          try {
            const info = await uc.table(t);
            return { read: readCheck(t, actor, {}), fix: fixCheck(t, actor, ownership(info.owner)) };
          } catch (err) {
            return {
              read: readCheck(t, actor, { error: (err as Error).message }),
              fix: fixCheck(t, actor, { mine: false }),
            };
          }
        })
      );
      checks.push(...results.map((r) => r.read), ...results.map((r) => r.fix));
      return checks;
    })
  );

  /**
   * Before tables are added: which of them, with the current sources, join together. Rules find
   * the joins; the model explains them. Only names and types go to the model, never rows.
   */
  app.post(
    '/api/projects/:id/sources/check',
    handle(async (req): Promise<RelationCheck> => {
      const actor = actorOf(req);
      const project = await projects.get(actor, idParam.parse(req.params).id);
      const { tables: picked } = checkBody.parse(req.body);
      const { sources } = await repo.view(project.id);
      const lower = (t: string) => t.toLowerCase();
      const all = [...new Set([...sources.map((s) => lower(s.fullName)), ...picked.map(lower)])];
      const columns = await schemaColumns(all, ucFor(req));
      const known = all.flatMap((t) => {
        const cols = [...columns].find(([name]) => lower(name) === t)?.[1];
        return cols ? [{ fullName: t, columns: cols }] : [];
      });
      const links = inferLinks(known);
      const groups = joinGroups(all, links);
      if (all.length < 2) return { links, groups, ai: null, aiError: null };
      try {
        const out = await callTool(
          relatePrompt,
          relateRequest(
            known.map((k) => ({ table: k.fullName, columns: k.columns.map(({ name, type }) => ({ name, type })) })),
            links
          ),
          llmFor(req)
        );
        const valid = new Set(all);
        return {
          links,
          groups,
          ai: { ...out, tables: out.tables.filter((t) => valid.has(lower(t.table))) },
          aiError: null,
        };
      } catch (err) {
        return { links, groups, ai: null, aiError: (err as Error).message.slice(0, 300) };
      }
    })
  );
}
