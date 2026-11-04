import type { Application, Request } from 'express';
import { z } from 'zod';
import type { LakebasePool } from '@databricks/appkit';
import { chatSchema, intakeSchema, newProjectSchema, refineSchema } from '../../shared/brief';
import type {
  BriefVersion,
  NewProject,
  Project,
  IntakeReply,
  ProjectDetail,
  ProjectSummary,
  SubProjectStage,
  SubProjectSummary,
} from '../../shared/brief';
import { callTool } from '../llm/llm';
import type { LlmDeps } from '../llm/llm';
import { draftBriefPrompt, draftBriefRequest, refineBriefPrompt, refineBriefRequest } from '../llm/prompts/brief';
import type { BriefOutput } from '../llm/prompts/brief';
import { chatBriefRequest, intakeChatPrompt, intakeChatRequest, mentionedTables } from '../llm/prompts/intake';
import { actorOf, handle, HttpError } from './http';

type Db = Pick<LakebasePool, 'query' | 'connect'>;

interface ProjectRow {
  id: string;
  parent_id: string | null;
  name: string;
  description: string | null;
  created_by: string;
  created_at: Date;
}

interface SummaryRow extends ProjectRow {
  brief_status: 'draft' | 'confirmed' | null;
  draft_status: 'draft' | 'validated' | null;
  sources: number;
  last_activity: Date;
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
  parentId: r.parent_id,
  name: r.name,
  description: r.description,
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

const PROJECT_COLUMNS = 'id, parent_id, name, description, created_by, created_at';

const stageOf = (r: SummaryRow): SubProjectStage =>
  r.draft_status === 'validated'
    ? 'validated'
    : r.draft_status
      ? 'design'
      : r.brief_status === 'confirmed'
        ? 'sources'
        : 'intent';

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

    /** Top-level projects of the actor, each with its sub-projects and their stage. */
    async list(actor: string): Promise<ProjectSummary[]> {
      const { rows } = await db.query<SummaryRow>(
        `SELECT p.id, p.parent_id, p.name, p.description, p.created_by, p.created_at,
           (SELECT status FROM gsb.semantic_brief b WHERE b.project_id = p.id ORDER BY version DESC LIMIT 1) AS brief_status,
           (SELECT status FROM gsb.metric_view_draft d WHERE d.project_id = p.id ORDER BY version DESC LIMIT 1) AS draft_status,
           (SELECT count(*)::int FROM gsb.source s WHERE s.project_id = p.id) AS sources,
           GREATEST(p.created_at,
             (SELECT MAX(created_at) FROM gsb.semantic_brief b WHERE b.project_id = p.id),
             (SELECT MAX(created_at) FROM gsb.metric_view_draft d WHERE d.project_id = p.id)) AS last_activity
         FROM gsb.project p WHERE p.created_by = $1 ORDER BY p.created_at DESC LIMIT 500`,
        [actor]
      );
      const children = new Map<string, SubProjectSummary[]>();
      for (const r of rows.filter((x) => x.parent_id)) {
        const list = children.get(r.parent_id!) ?? [];
        list.push({
          ...toProject(r),
          stage: stageOf(r),
          sources: r.sources,
          lastActivity: r.last_activity.toISOString(),
        });
        children.set(r.parent_id!, list);
      }
      return rows.filter((r) => !r.parent_id).map((r) => ({ ...toProject(r), subProjects: children.get(r.id) ?? [] }));
    },

    async create(actor: string, p: NewProject, parentId: string | null = null): Promise<Project> {
      const { rows } = await db.query<ProjectRow>(
        `INSERT INTO gsb.project (name, description, parent_id, created_by)
         VALUES ($1, $2, $3, $4) RETURNING ${PROJECT_COLUMNS}`,
        [p.name, p.description ?? null, parentId, actor]
      );
      await audit(actor, parentId ? 'create_subproject' : 'create_project', rows[0].id, { name: p.name, parentId });
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

  app.post(
    '/api/projects/:id/subprojects',
    handle(async (req) => {
      const actor = actorOf(req);
      const parent = await repo.get(actor, idParam.parse(req.params).id);
      if (parent.parentId) throw new HttpError(400, 'A sub-project cannot have sub-projects.');
      return repo.create(actor, newProjectSchema.parse(req.body), parent.id);
    })
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

  /** One interview turn. The conversation lives in the browser until the user saves a draft. */
  app.post(
    '/api/projects/:id/intake/chat',
    handle(async (req): Promise<IntakeReply> => {
      const project = await repo.get(actorOf(req), idParam.parse(req.params).id);
      const { messages } = chatSchema.parse(req.body);
      const turn = await callTool(intakeChatPrompt, intakeChatRequest(project.description, messages), llmFor(req));
      const allowed = new Set(mentionedTables(messages));
      const sources = turn.brief.candidateSources?.filter((t) => allowed.has(t.toLowerCase()));
      return { ...turn, brief: { ...turn.brief, ...(sources ? { candidateSources: sources } : {}) } };
    })
  );

  app.post(
    '/api/projects/:id/intake/save',
    handle(async (req) => {
      const actor = actorOf(req);
      const project = await repo.get(actor, idParam.parse(req.params).id);
      const { messages } = chatSchema.parse(req.body);
      const output = await callTool(draftBriefPrompt, chatBriefRequest(project.description, messages), llmFor(req));
      const allowed = new Set(mentionedTables(messages));
      output.brief.candidateSources = output.brief.candidateSources.filter((t) => allowed.has(t.toLowerCase()));
      return repo.addDraft(actor, project.id, output, { chat: messages.length });
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
