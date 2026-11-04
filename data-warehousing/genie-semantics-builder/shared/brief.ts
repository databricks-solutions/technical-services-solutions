import { z } from 'zod';

/** UC names: three parts, letters, digits, underscore or hyphen. Backticks are added when SQL is built. */
const NAME_PART = '[A-Za-z0-9_][A-Za-z0-9_-]{0,254}';
export const UC_NAME_PART = new RegExp(`^${NAME_PART}$`);
export const UC_TABLE_NAME = new RegExp(`^${NAME_PART}\\.${NAME_PART}\\.${NAME_PART}$`);

const text = (max: number) => z.string().trim().max(max);
const named = z.object({ name: text(100).min(1), description: text(1000) });

export const semanticBriefSchema = z.object({
  title: text(200).min(1),
  businessGoal: text(2000).min(1),
  audience: z.array(text(200)).max(20),
  keyQuestions: z.array(text(500)).min(1).max(30),
  measures: z
    .array(
      named.extend({
        aggregation: z.enum(['sum', 'count', 'count_distinct', 'avg', 'min', 'max', 'ratio', 'other']),
      })
    )
    .max(50),
  dimensions: z.array(named).max(50),
  timeGrains: z.array(z.enum(['day', 'week', 'month', 'quarter', 'year'])).max(5),
  candidateSources: z.array(z.string().regex(UC_TABLE_NAME)).max(30),
  glossary: z.array(z.object({ term: text(100).min(1), definition: text(1000) })).max(50),
  assumptions: z.array(text(500)).max(30),
  openQuestions: z.array(text(500)).max(30),
});
export type SemanticBrief = z.infer<typeof semanticBriefSchema>;

export const intakeSchema = z.object({
  goal: text(4000).min(10, 'Describe the goal in at least 10 characters'),
  audience: text(1000).optional(),
  questions: text(4000).optional(),
  terms: text(4000).optional(),
  sources: z.array(z.string().trim().regex(UC_TABLE_NAME, 'Use catalog.schema.table')).max(30),
});
export type IntakeInput = z.infer<typeof intakeSchema>;

export const refineSchema = z.object({ instruction: text(2000).min(3) });

export const newProjectSchema = z.object({
  name: text(200).min(1, 'Name is required'),
  description: text(4000).optional(),
});
export type NewProject = z.infer<typeof newProjectSchema>;

export interface Project {
  id: string;
  /** Set for a sub-project. A sub-project holds one brief, its sources and its metric view designs. */
  parentId: string | null;
  name: string;
  description: string | null;
  createdBy: string;
  createdAt: string;
}

export type SubProjectStage = 'intent' | 'sources' | 'design' | 'validated';

export interface SubProjectSummary extends Project {
  stage: SubProjectStage;
  sources: number;
  lastActivity: string;
}

export interface ProjectSummary extends Project {
  subProjects: SubProjectSummary[];
}

export interface BriefVersion {
  version: number;
  status: 'draft' | 'confirmed';
  brief: SemanticBrief;
  summary: string;
  createdAt: string;
  confirmedAt: string | null;
}

export interface ProjectDetail {
  project: Project;
  brief: BriefVersion | null;
}

export interface UcTable {
  name: string;
  type: string;
}

export const chatSchema = z.object({
  messages: z
    .array(z.object({ role: z.enum(['user', 'assistant']), content: text(4000).min(1) }))
    .min(1)
    .max(40),
});
export type ChatMessage = z.infer<typeof chatSchema>['messages'][number];

export interface IntakeReply {
  reply: string;
  suggestions: string[];
  brief: Partial<SemanticBrief>;
  ready: boolean;
  /** Metric views the AI proposes from the source tables. Empty unless it is proposing. */
  ideas: MetricIdea[];
}

/** What a delete removes. cleanup drops sandbox views the project may have left in Unity Catalog. */
export interface DeletePlan {
  name: string;
  subProjects: string[];
  cleanup: string[];
}

export interface MemoryItem {
  id: string;
  kind: 'term' | 'assumption';
  text: string;
  detail: string | null;
  /** Sub-project whose confirmed brief added it. */
  fromName: string | null;
}

/** What the intake chat starts from: the assessed tables, the saved chat, and the project memory. */
export interface IntakeContext {
  tables: string[];
  session: ChatMessage[];
  memory: MemoryItem[];
}

export interface MetricIdea {
  title: string;
  question: string;
  measures: string[];
  dimensions: string[];
}
