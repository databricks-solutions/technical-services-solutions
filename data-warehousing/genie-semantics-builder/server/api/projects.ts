import type { Application, Request } from 'express';
import { z } from 'zod';
import type { LakebasePool } from '@databricks/appkit';
import { intakeSchema, newProjectSchema, refineSchema } from '../../shared/brief';
import type { BriefVersion, NewProject, Project, ProjectDetail } from '../../shared/brief';
import { callTool } from '../llm/llm';
import type { LlmDeps } from '../llm/llm';
import { draftBriefPrompt, draftBriefRequest, refineBriefPrompt, refineBriefRequest } from '../llm/prompts/brief';
import type { BriefOutput } from '../llm/prompts/brief';
import { actorOf, handle, HttpError } from './http';

type Db = Pick<LakebasePool, 'query' | 'connect'>;

interface ProjectRow {
  id: string;
  name: string;
  description: string | null;
  target_catalog: string | null;
  target_schema: string | null;
  created_by: string;
  created_at: Date;
}

interface BriefRow {
  version: number;
  status: 'draft' | 'confirmed';
  content: { brief: BriefVersion['brief']; summary: string };
  created_at: Date;
  confirmed_at: Date | null;
}

const toProject = (r: ProjectRow): Project => ({
  id: r.id,
  name: r.name,
  description: r.description,
  targetCatalog: r.target_catalog,
  targetSchema: r.target_schema,
  createdBy: r.created_by,
  createdAt: r.created_at.toISOString(),
});

const toBrief = (r: BriefRow): BriefVersion => ({
  version: r.version,
  status: r.status,
  brief: r.content.brief,
  summary: r.content.summary,
  createdAt: r.created_at.toISOString(),
  confirmedAt: r.confirmed_at?.toISOString() ?? null,
});

const PROJECT_COLUMNS = 'id, name, description, target_catalog, target_schema, created_by, created_at';

/** Projects are private to their creator. Every query filters on created_by. */
export function projectRepo(db: Db) {
  async function audit(actor: string, action: string, projectId: string, detail?: Record<string, unknown>) {
    await db.query(
      `INSERT INTO gsb.audit_log (actor, action, project_id, outcome, detail) VALUES ($1, $2, $3, 'succeeded', $4)`,
      [actor, action, projectId, detail ?? null]
    );
  }

  async function get(actor: string, id: string): Promise<Project> {
    const { rows } = await db.query<ProjectRow>(
      `SELECT ${PROJECT_COLUMNS} FROM gsb.project WHERE id = $1 AND created_by = $2`,
      [id, actor]
    );
    if (!rows[0]) throw new HttpError(404, 'Project not found.');
    return toProject(rows[0]);
  }

  async function latestBrief(projectId: string): Promise<BriefVersion | null> {
    const { rows } = await db.query<BriefRow>(
      `SELECT version, status, content, created_at, confirmed_at FROM gsb.semantic_brief
       WHERE project_id = $1 ORDER BY version DESC LIMIT 1`,
      [projectId]
    );
    return rows[0] ? toBrief(rows[0]) : null;
  }

  return {
    get,
    latestBrief,

    async list(actor: string): Promise<Project[]> {
      const { rows } = await db.query<ProjectRow>(
        `SELECT ${PROJECT_COLUMNS} FROM gsb.project WHERE created_by = $1 ORDER BY created_at DESC LIMIT 200`,
        [actor]
      );
      return rows.map(toProject);
    },

    async create(actor: string, p: NewProject): Promise<Project> {
      const { rows } = await db.query<ProjectRow>(
        `INSERT INTO gsb.project (name, description, target_catalog, target_schema, created_by)
         VALUES ($1, $2, $3, $4, $5) RETURNING ${PROJECT_COLUMNS}`,
        [p.name, p.description ?? null, p.targetCatalog ?? null, p.targetSchema ?? null, actor]
      );
      await audit(actor, 'create_project', rows[0].id, { name: p.name });
      return toProject(rows[0]);
    },

    async addDraft(actor: string, projectId: string, output: BriefOutput, input: unknown): Promise<BriefVersion> {
      const { rows } = await db.query<BriefRow>(
        `INSERT INTO gsb.semantic_brief (project_id, version, content, created_by)
         SELECT $1, COALESCE(MAX(version), 0) + 1, $2, $3 FROM gsb.semantic_brief WHERE project_id = $1
         RETURNING version, status, content, created_at, confirmed_at`,
        [projectId, { ...output, input }, actor]
      );
      return toBrief(rows[0]);
    },

    /** Confirms the latest draft and registers its candidate sources, in one transaction. */
    async confirm(actor: string, projectId: string, version: number): Promise<BriefVersion> {
      const client = await db.connect();
      try {
        await client.query('BEGIN');
        const { rows } = await client.query<BriefRow>(
          `UPDATE gsb.semantic_brief SET status = 'confirmed', confirmed_by = $3, confirmed_at = now()
           WHERE project_id = $1 AND version = $2 AND status = 'draft'
             AND version = (SELECT MAX(version) FROM gsb.semantic_brief WHERE project_id = $1)
           RETURNING version, status, content, created_at, confirmed_at`,
          [projectId, version, actor]
        );
        if (!rows[0]) throw new HttpError(409, 'Only the latest draft can be confirmed.');
        const brief = toBrief(rows[0]);
        await client.query(
          `INSERT INTO gsb.source (project_id, full_name, added_by)
           SELECT $1, unnest($2::text[]), $3 ON CONFLICT (project_id, full_name) DO NOTHING`,
          [projectId, brief.brief.candidateSources, actor]
        );
        await client.query(
          `INSERT INTO gsb.audit_log (actor, action, project_id, outcome, detail) VALUES ($1, 'confirm_brief', $2, 'succeeded', $3)`,
          [actor, projectId, { version }]
        );
        await client.query('COMMIT');
        return brief;
      } catch (err) {
        await client.query('ROLLBACK');
        throw err;
      } finally {
        client.release();
      }
    },
  };
}

const idParam = z.object({ id: z.uuid() });
const versionParam = idParam.extend({ version: z.coerce.number().int().positive() });

/** Lakebase is app-only, so handlers run in app scope. Only the model call opens a user scope. */
export function registerProjectRoutes(app: Application, db: Db, llmFor: (req: Request) => LlmDeps) {
  const repo = projectRepo(db);

  app.get(
    '/api/projects',
    handle((req) => repo.list(actorOf(req)))
  );

  app.post(
    '/api/projects',
    handle((req) => repo.create(actorOf(req), newProjectSchema.parse(req.body)))
  );

  app.get(
    '/api/projects/:id',
    handle(async (req): Promise<ProjectDetail> => {
      const project = await repo.get(actorOf(req), idParam.parse(req.params).id);
      return { project, brief: await repo.latestBrief(project.id) };
    })
  );

  app.post(
    '/api/projects/:id/briefs',
    handle(async (req) => {
      const actor = actorOf(req);
      const project = await repo.get(actor, idParam.parse(req.params).id);
      const input = intakeSchema.parse(req.body);
      const output = await callTool(draftBriefPrompt, draftBriefRequest(input), llmFor(req));
      return repo.addDraft(actor, project.id, output, input);
    })
  );

  app.post(
    '/api/projects/:id/briefs/refine',
    handle(async (req) => {
      const actor = actorOf(req);
      const project = await repo.get(actor, idParam.parse(req.params).id);
      const { instruction } = refineSchema.parse(req.body);
      const current = await repo.latestBrief(project.id);
      if (!current) throw new HttpError(409, 'Create a brief before you refine it.');
      const output = await callTool(refineBriefPrompt, refineBriefRequest(current.brief, instruction), llmFor(req));
      return repo.addDraft(actor, project.id, output, { instruction, from: current.version });
    })
  );

  app.post(
    '/api/projects/:id/briefs/:version/confirm',
    handle(async (req) => {
      const actor = actorOf(req);
      const { id, version } = versionParam.parse(req.params);
      const project = await repo.get(actor, id);
      return repo.confirm(actor, project.id, version);
    })
  );
}
