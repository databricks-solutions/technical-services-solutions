import { z } from 'zod';
import { untrusted } from '../llm';
import type { ToolPrompt } from '../llm';

const text = (max: number) => z.string().trim().max(max);

const tuneOutput = z.object({
  kind: z
    .enum(['instruction', 'example', 'synonym', 'description'])
    .describe('The one change to make. Choose the smallest change that fixes the wrong answer.'),
  text: text(500).describe('For instruction: one rule line for Genie. For description: the new field description.'),
  field: text(255).describe('For synonym or description: the exact field name from the input. Else empty.'),
  synonyms: z.array(text(60)).max(5).describe('For synonym: the words users type for the field. Else empty.'),
  question: text(300).describe('For example: a new question, not a benchmark question. Else empty.'),
  measures: z.array(text(255)).max(4).describe('For example: exact measure names that answer the question.'),
  dimensions: z.array(text(255)).max(3).describe('For example: exact dimension names to group by.'),
  rationale: text(400).describe('Why Genie answered wrong, and why this change helps. Plain words, no SQL.'),
});
export type TuneOutput = z.infer<typeof tuneOutput>;

export const tunePrompt: ToolPrompt<TuneOutput> = {
  id: 'genie.tune',
  version: 1,
  system: `You improve a Databricks Genie space on one Unity Catalog metric view.
Genie answered a benchmark question wrong. You get the question, the expected SQL, the SQL Genie wrote, the fields of
the view with their descriptions and synonyms, and the current instructions. You never get result values.
Suggest exactly one change:
- instruction: a short rule, such as how to read a business term or which field to filter on.
- synonym: words users type for a field, when Genie picked the wrong field.
- description: a better field description, when the field meaning was not clear.
- example: a new example question with the measures and dimensions that answer it. The server writes its SQL.
Rules:
- Use only exact field names from the input. Never invent fields. Never write SQL.
- Do not copy the benchmark question or its answer into the change: the benchmark must still test Genie.`,
  tool: {
    name: 'submit_space_change',
    description: 'Submit one change to the Genie space settings.',
    schema: tuneOutput,
  },
  maxTokens: 1500,
};

export const tuneRequest = (input: {
  question: string;
  expectedSql: string | null;
  genieSql: string | null;
  fields: { name: string; kind: 'measure' | 'dimension'; description: string; synonyms: string[] }[];
  instructions: string[];
}) =>
  [
    'Suggest one change so that Genie answers this benchmark question right.',
    untrusted('benchmark_question', input.question),
    untrusted('expected_sql', input.expectedSql ?? 'none'),
    untrusted('genie_sql', input.genieSql ?? 'Genie wrote no SQL.'),
    untrusted('fields', JSON.stringify(input.fields)),
    untrusted('instructions', input.instructions.join('\n')),
  ].join('\n\n');
