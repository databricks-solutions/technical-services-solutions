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
  targetCatalog: z.string().trim().regex(UC_NAME_PART).optional(),
  targetSchema: z.string().trim().regex(UC_NAME_PART).optional(),
});
export type NewProject = z.infer<typeof newProjectSchema>;

export interface Project {
  id: string;
  name: string;
  description: string | null;
  targetCatalog: string | null;
  targetSchema: string | null;
  createdBy: string;
  createdAt: string;
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
