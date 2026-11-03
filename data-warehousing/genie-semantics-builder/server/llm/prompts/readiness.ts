import { z } from 'zod';
import type { SemanticBrief } from '../../../shared/brief';
import type { ReadinessCheck } from '../../../shared/readiness';
import type { TableProfile } from '../../readiness/profile';
import { untrusted } from '../llm';
import type { ToolPrompt } from '../llm';

const text = (max: number) => z.string().trim().max(max);

const assessmentOutput = z.object({
  role: z
    .enum(['fact', 'dimension', 'unknown'])
    .describe('fact: events or transactions with measures; dimension: entities to group by.'),
  score: z
    .number()
    .int()
    .min(0)
    .max(100)
    .describe(
      'Readiness of this table for the metric views in the brief. 80+ ready, 50-79 needs work, below 50 not ready.'
    ),
  summary: text(600).describe('Two or three sentences for the user about this table.'),
  findings: z.array(text(300)).max(8).describe('Specific issues or strengths, most important first.'),
  tableComment: text(500)
    .nullable()
    .describe('A business description for the table. null if the table already has one.'),
  columnComments: z
    .array(z.object({ column: text(255), comment: text(300) }))
    .max(100)
    .describe('Business descriptions for columns that have no comment. Use exact column names.'),
  primaryKey: z
    .array(text(255))
    .max(4)
    .nullable()
    .describe(
      'Columns that uniquely identify a row, only if the table has no primary key and the key is clear from the names.'
    ),
  foreignKeys: z
    .array(
      z.object({
        columns: z.array(text(255)).min(1).max(4),
        references: text(800).describe('Full name of another table in the project.'),
        refColumns: z.array(text(255)).min(1).max(4),
      })
    )
    .max(10)
    .describe('Joins to other project tables that are not declared yet.'),
});
export type AssessmentOutput = z.infer<typeof assessmentOutput>;

export const assessSourcePrompt: ToolPrompt<AssessmentOutput> = {
  id: 'readiness.assess',
  version: 1,
  system: `You are a semantic modeling advisor for Databricks Unity Catalog metric views.
Assess one source table against a confirmed Semantic Brief and propose metadata fixes.
Rules:
- Use only the columns and tables you receive. Use exact column and table names. Never invent names.
- Base the score on fit for the brief: the needed measures and dimensions, the time grains, descriptions, and declared keys.
- Write descriptions in plain business language, one sentence each, without SQL.
- Propose a primary key only when the column names make the key clear, for example an id or key column.
- Propose a foreign key only to a table in other_project_tables, on its key columns.
- Do not write SQL. The app builds and validates the statements.`,
  tool: {
    name: 'submit_source_assessment',
    description: 'Submit the readiness assessment and the proposed metadata fixes for one table.',
    schema: assessmentOutput,
  },
  maxTokens: 8000,
};

const describeTable = (p: TableProfile) => ({
  table: p.fullName,
  comment: p.comment || null,
  columns: p.columns.map((c) => ({ name: c.name, type: c.type, comment: c.comment || null })),
  primaryKey: p.primaryKey,
  foreignKeys: p.foreignKeys,
});

export function assessSourceRequest(
  brief: SemanticBrief,
  table: TableProfile,
  checks: ReadinessCheck[],
  others: TableProfile[]
): string {
  const scope = {
    title: brief.title,
    businessGoal: brief.businessGoal,
    measures: brief.measures,
    dimensions: brief.dimensions,
    timeGrains: brief.timeGrains,
  };
  return [
    'Assess this table for the Semantic Brief.',
    untrusted('semantic_brief', JSON.stringify(scope, null, 2)),
    untrusted('table', JSON.stringify(describeTable(table), null, 2)),
    untrusted('deterministic_checks', JSON.stringify(checks.map(({ id, status, detail }) => ({ id, status, detail })))),
    untrusted(
      'other_project_tables',
      JSON.stringify(
        others.map((o) => ({ table: o.fullName, columns: o.columns.map((c) => c.name), primaryKey: o.primaryKey }))
      )
    ),
  ].join('\n\n');
}
