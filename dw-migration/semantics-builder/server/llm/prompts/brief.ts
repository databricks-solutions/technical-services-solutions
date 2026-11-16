import { z } from 'zod';
import { semanticBriefSchema } from '../../../shared/brief';
import type { IntakeInput, SemanticBrief } from '../../../shared/brief';
import { untrusted } from '../llm';
import type { ToolPrompt } from '../llm';

const briefOutput = z.object({
  brief: semanticBriefSchema,
  summary: z
    .string()
    .trim()
    .max(1000)
    .describe('Two or three sentences for the user: what the brief covers and what is still open.'),
});
export type BriefOutput = z.infer<typeof briefOutput>;

const SYSTEM = `You are a semantic modeling advisor for Databricks Unity Catalog metric views.
Turn a business request into a Semantic Brief: the goal, the audience, the questions to answer, the measures (with their aggregation), the dimensions, the time grains, and a glossary of business terms.
Rules:
- Use business-friendly names in Title Case for measures and dimensions, for example "Total Revenue" or "Order Date".
- candidateSources may only contain tables that the user named. Never invent table names.
- Do not guess column names or SQL. Source analysis happens in a later step.
- If something is ambiguous or missing, record it in openQuestions instead of guessing. Record what you inferred in assumptions.
- Keep every text short and specific.
- metric_dictionary, when given, holds the team's own definitions. Use its names, definitions and synonyms for
  measures, dimensions and the glossary. Keep the exact names of certified entries.`;

export const draftBriefPrompt: ToolPrompt<BriefOutput> = {
  id: 'brief.draft',
  version: 2,
  system: SYSTEM,
  tool: {
    name: 'submit_semantic_brief',
    description: 'Submit the Semantic Brief and a short summary for the user.',
    schema: briefOutput,
  },
};

export const refineBriefPrompt: ToolPrompt<BriefOutput> = {
  ...draftBriefPrompt,
  id: 'brief.refine',
  system: `${SYSTEM}\nYou receive the current brief and a change request. Apply the change, keep everything else, and summarize what changed.`,
};

export function draftBriefRequest(input: IntakeInput): string {
  return [
    'Create a Semantic Brief from this request.',
    untrusted('business_goal', input.goal),
    input.audience ? untrusted('audience', input.audience) : '',
    input.questions ? untrusted('key_questions', input.questions) : '',
    input.terms ? untrusted('business_terms', input.terms) : '',
    untrusted('candidate_sources', input.sources.length ? input.sources.join('\n') : '(none named)'),
  ]
    .filter(Boolean)
    .join('\n\n');
}

export function refineBriefRequest(current: SemanticBrief, instruction: string): string {
  return [
    'Update this Semantic Brief with the change request.',
    untrusted('current_brief', JSON.stringify(current, null, 2)),
    untrusted('change_request', instruction),
  ].join('\n\n');
}
