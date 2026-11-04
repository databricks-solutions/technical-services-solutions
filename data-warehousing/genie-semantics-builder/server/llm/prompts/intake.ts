import { z } from 'zod';
import { semanticBriefSchema } from '../../../shared/brief';
import type { ChatMessage } from '../../../shared/brief';
import { untrusted } from '../llm';
import type { ToolPrompt } from '../llm';

const turnOutput = z.object({
  reply: z
    .string()
    .trim()
    .min(1)
    .max(2000)
    .describe('Your next message: a short acknowledgment, then exactly one question, with a suggested answer.'),
  suggestions: z
    .array(z.string().trim().min(1).max(200))
    .max(4)
    .describe('Short answers the user can click, in their words.'),
  brief: semanticBriefSchema
    .partial()
    .describe('The brief so far. Leave out fields you do not know yet. Never invent table names.'),
  ready: z.boolean().describe('True when goal, key questions, measures and dimensions are known.'),
});
export type IntakeTurn = z.infer<typeof turnOutput>;

export const intakeChatPrompt: ToolPrompt<IntakeTurn> = {
  id: 'intake.chat',
  version: 1,
  system: `You are a semantic modeling advisor for Databricks Unity Catalog metric views.
Interview a business user to write a Semantic Brief for one metric view. Cover, in this order and one question per turn:
1. the business goal, 2. the audience, 3. the key questions to answer, 4. the measures and how they aggregate,
5. the dimensions and time grains, 6. business terms, 7. the source tables.
Rules:
- Ask one question per turn. Offer a concrete suggested answer based on what you know, so the user can confirm it.
- Keep replies under 80 words, friendly and plain. No SQL.
- Users mention tables as @catalog.schema.table. candidateSources may contain only tables the user mentioned.
- Use Title Case business names for measures and dimensions.
- Record what you inferred in assumptions and what is unclear in openQuestions.
- When you have enough, set ready to true and tell the user to save the draft. They can keep chatting to refine it.`,
  tool: {
    name: 'submit_intake_turn',
    description: 'Submit your next chat message, quick replies, and the brief so far.',
    schema: turnOutput,
  },
  maxTokens: 4000,
};

const transcript = (messages: ChatMessage[]) =>
  messages.map((m) => `${m.role === 'user' ? 'User' : 'Advisor'}: ${m.content}`).join('\n\n');

export const intakeChatRequest = (projectGoal: string | null, messages: ChatMessage[]) =>
  [
    'Continue the interview.',
    projectGoal ? untrusted('sub_project_goal', projectGoal) : '',
    untrusted('conversation', transcript(messages)),
  ]
    .filter(Boolean)
    .join('\n\n');

export const chatBriefRequest = (projectGoal: string | null, messages: ChatMessage[]) =>
  [
    'Create the Semantic Brief from this interview.',
    projectGoal ? untrusted('sub_project_goal', projectGoal) : '',
    untrusted('conversation', transcript(messages)),
  ]
    .filter(Boolean)
    .join('\n\n');

/** Tables the user named with @catalog.schema.table. Only these may become candidate sources. */
export function mentionedTables(messages: ChatMessage[]): string[] {
  const names = messages
    .filter((m) => m.role === 'user')
    .flatMap((m) => [
      ...m.content.matchAll(/@([A-Za-z0-9_][A-Za-z0-9_-]*\.[A-Za-z0-9_][A-Za-z0-9_-]*\.[A-Za-z0-9_][A-Za-z0-9_-]*)/g),
    ])
    .map((m) => m[1].toLowerCase());
  return [...new Set(names)];
}
