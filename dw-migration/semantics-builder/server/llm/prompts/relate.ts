import { z } from 'zod';
import type { Link } from '../../../shared/readiness';
import { untrusted } from '../llm';
import type { ToolPrompt } from '../llm';

const text = (max: number) => z.string().trim().max(max);

const relateOutput = z.object({
  summary: text(600).describe(
    'Two or three plain sentences: what these tables describe together, and if they fit one model.'
  ),
  tables: z
    .array(
      z.object({
        table: text(800).describe('Exact full table name from the input.'),
        belongs: z.boolean().describe('True if the table fits one metric view with the main group.'),
        reason: text(300).describe('Why, in business words. Mention the join column when there is one.'),
      })
    )
    .max(30),
  suggestion: text(400).describe('What to do, such as "Model returns in a separate sub-project". Empty if all fit.'),
});
export type RelateOutput = z.infer<typeof relateOutput>;

export const relatePrompt: ToolPrompt<RelateOutput> = {
  id: 'sources.relate',
  version: 1,
  system: `You are a semantic modeling advisor for Databricks Unity Catalog metric views.
A user selected tables for one metric view. Explain which tables belong together in one star or snowflake model.
Rules:
- A metric view has one fact table and joins to dimension tables. Tables that do not join to the fact belong elsewhere.
- Use the detected joins first; you can also infer a join from column names and types. Never invent tables or columns.
- Use only exact table names from the input. Plain language, no SQL.`,
  tool: {
    name: 'submit_table_relations',
    description: 'Submit how the selected tables relate and what to do.',
    schema: relateOutput,
  },
  maxTokens: 3000,
};

export const relateRequest = (tables: { table: string; columns: { name: string; type: string }[] }[], links: Link[]) =>
  [
    'Explain how these selected tables relate.',
    untrusted('tables', JSON.stringify(tables)),
    untrusted('detected_joins', JSON.stringify(links)),
  ].join('\n\n');
