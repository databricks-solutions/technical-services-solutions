import { createHash } from 'node:crypto';
import type { Application, Request } from 'express';
import { z } from 'zod';
import type { LakebasePool } from '@databricks/appkit';
import { domainSchema, pageEditSchema, pageKeySchema, pagesScript } from '../../shared/pages';
import type { DomainList, PageDraft, PagesView } from '../../shared/pages';
import { validateMetricView } from '../../shared/metricView';
import { loadDictionary } from '../dictionary/store';
import { buildPages } from '../pages/build';
import type { DomainsDeps } from '../pages/domains';
import { actorOf, handle, HttpError } from './http';
import { designerRepo } from './designer';
import { projectRepo } from './projects';

type Db = Pick<LakebasePool, 'query' | 'connect'>;
const idParam = z.object({ id: z.uuid() });
const exportedBody = z.object({ pages: z.number().int().min(0).max(500) });
/** A fixed UUID (version 4 layout) for each Page of a sub-project, so a second run of the script makes no copy. */
export function requestIdOf(projectId: string, key: string): string {
  const h = createHash('sha256').update(`${projectId}\n${key}`).digest('hex');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-4${h.slice(13, 16)}-${((parseInt(h[16], 16) & 3) | 8).toString(16)}${h.slice(17, 20)}-${h.slice(20, 32)}`;
}
type Edit = Pick<PageDraft, 'title' | 'synonyms' | 'description' | 'body' | 'include'>;

/**
 * Pages for UC Semantics Discover. The app drafts them from its own content and the user edits them. Apps cannot get
 * the knowledge scope of the Pages API, so the user downloads one file for Genie Code bulk import, or runs the script
 * of API calls as themselves. Nothing is written to Discover from here.
 */
export function registerPagesRoutes(app: Application, db: Db, domains: DomainsDeps) {
  const projects = projectRepo(db);
  const designs = designerRepo(db);

  async function view(req: Request): Promise<PagesView & { topId: string }> {
    const actor = actorOf(req);
    const sub = await projects.get(actor, idParam.parse(req.params).id);
    const top = sub.parentId ? await projects.get(actor, sub.parentId) : sub;
    const [brief, dictionary, draft, meta, edits] = await Promise.all([
      projects.latestBrief(sub.id),
      loadDictionary(db, sub.id),
      designs.view(sub.id).then((v) => v.draft),
      db.query<{
        domain: string | null;
        target: string | null;
        promoted: boolean;
        file: string | null;
        tables: string[];
      }>(
        `SELECT t.pages_domain AS domain, s.promotion_target AS target,
           EXISTS (SELECT 1 FROM gsb.promotion pr WHERE pr.project_id = s.id AND pr.status = 'succeeded'
                     AND pr.target = s.promotion_target) AS promoted,
           (SELECT source_file FROM gsb.dictionary_entry WHERE project_id = t.id LIMIT 1) AS file,
           ARRAY(SELECT full_name FROM gsb.source WHERE project_id = s.id ORDER BY full_name) AS tables
         FROM gsb.project s JOIN gsb.project t ON t.id = $2 WHERE s.id = $1`,
        [sub.id, top.id]
      ),
      db.query<{ key: string; content: Edit }>('SELECT key, content FROM gsb.page_edit WHERE project_id = $1', [
        sub.id,
      ]),
    ]);
    const m = meta.rows[0];
    const generated = buildPages({
      project: top.name,
      subProject: sub.name,
      brief: brief ? { brief: brief.brief, version: brief.version } : null,
      dictionary,
      dictionaryFile: m?.file ?? null,
      view: (draft && validateMetricView(draft.yaml).view) ?? null,
      target: m?.promoted ? m.target : null,
      sourceTables: m?.tables ?? [],
      includeEntity: true,
    });
    const byKey = new Map(edits.rows.map((e) => [e.key, e.content]));
    return {
      topId: top.id,
      domain: m?.domain ?? null,
      pages: generated.map((p) => {
        const e = byKey.get(p.key);
        return e ? { ...p, ...e, edited: true } : p;
      }),
    };
  }

  const audit = (actor: string, action: string, projectId: string, detail: unknown) =>
    db.query(
      `INSERT INTO gsb.audit_log (actor, action, project_id, outcome, detail) VALUES ($1, $2, $3, 'succeeded', $4)`,
      [actor, action, projectId, detail]
    );
  const strip = (v: PagesView & { topId: string }): PagesView => ({ domain: v.domain, pages: v.pages });

  /** A failure is not an error here: if the service principal cannot list the domains, the user types the name. */
  app.get(
    '/api/pages/domains',
    handle(async (req): Promise<DomainList> => {
      actorOf(req);
      try {
        return { domains: await domains.list(), error: null };
      } catch (err) {
        return { domains: [], error: (err as Error).message.slice(0, 300) };
      }
    })
  );

  app.get(
    '/api/projects/:id/pages',
    handle(async (req) => strip(await view(req)))
  );

  /** The domain lives on the top-level project, so every sub-project's Pages share it. */
  app.post(
    '/api/projects/:id/pages/domain',
    handle(async (req) => {
      const { domain } = domainSchema.parse(req.body);
      const v = await view(req);
      await db.query('UPDATE gsb.project SET pages_domain = $2 WHERE id = $1', [v.topId, domain]);
      await audit(actorOf(req), 'set_pages_domain', v.topId, { domain });
      return { ...strip(v), domain };
    })
  );

  app.post(
    '/api/projects/:id/pages/edit',
    handle(async (req) => {
      const actor = actorOf(req);
      const { key, ...content } = pageEditSchema.parse(req.body);
      const v = await view(req);
      if (!v.pages.some((p) => p.key === key)) throw new HttpError(404, 'This Page is not part of the sub-project.');
      const { id } = idParam.parse(req.params);
      await db.query(
        `INSERT INTO gsb.page_edit (project_id, key, content, updated_by) VALUES ($1, $2, $3, $4)
         ON CONFLICT (project_id, key) DO UPDATE SET content = EXCLUDED.content, updated_by = EXCLUDED.updated_by,
           updated_at = now()`,
        [id, key, JSON.stringify(content), actor]
      );
      return strip(await view(req));
    })
  );

  app.post(
    '/api/projects/:id/pages/reset',
    handle(async (req) => {
      const { key } = pageKeySchema.parse(req.body);
      await view(req);
      const { id } = idParam.parse(req.params);
      await db.query('DELETE FROM gsb.page_edit WHERE project_id = $1 AND key = $2', [id, key]);
      return strip(await view(req));
    })
  );

  /** The download happens in the browser; this keeps a record of it. */
  app.post(
    '/api/projects/:id/pages/exported',
    handle(async (req) => {
      const { pages } = exportedBody.parse(req.body);
      const { id } = idParam.parse(req.params);
      await view(req);
      await audit(actorOf(req), 'export_pages', id, { pages });
      return { ok: true };
    })
  );

  /**
   * The script that creates the included Pages as drafts with the Knowledge Pages API. The user runs it as
   * themselves; the app cannot call the API (apps cannot get the knowledge scope).
   */
  app.post(
    '/api/projects/:id/pages/commands',
    handle(async (req) => {
      const v = await view(req);
      if (!v.domain) throw new HttpError(409, 'Save a domain first.');
      const included = v.pages.filter((p) => p.include);
      if (!included.length) throw new HttpError(409, 'Include at least one Page.');
      const { id } = idParam.parse(req.params);
      const script = pagesScript(
        v.domain,
        included.map((p) => ({ ...p, requestId: requestIdOf(id, p.key) }))
      );
      await audit(actorOf(req), 'prepare_pages_commands', id, { pages: included.length });
      return { script, pages: included.length };
    })
  );
}
