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
  ideas: z
    .array(
      z.object({
        title: z.string().trim().min(1).max(100).describe('Short name, such as "Revenue performance".'),
        question: z.string().trim().max(300).describe('The main business question it answers.'),
        measures: z
          .array(z.string().trim().max(100))
          .max(8)
          .describe('Title Case measure names, each with its column.'),
        dimensions: z.array(z.string().trim().max(100)).max(8).describe('Title Case dimension names.'),
      })
    )
    .max(5)
    .describe('Metric views you can build from source_tables. Fill only when proposing options; else empty.'),
});
export type IntakeTurn = z.infer<typeof turnOutput>;

export const intakeChatPrompt: ToolPrompt<IntakeTurn> = {
  id: 'intake.chat',
  version: 2,
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
- source_tables lists the tables the user already chose, with columns and keys (metadata only). When the user does
  not know the goal or asks what can be built, propose 3 to 5 ideas from these tables, each using real columns, and
  ask which one to build. When the user picks one, use it to fill the brief and continue the interview.
- The candidate sources are the source tables and any table the user mentions.
- project_memory holds terms and assumptions confirmed in other sub-projects of the same project. Reuse their
  definitions, say so when you do, and do not ask again what they already answer.
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

/** Table metadata and memory the model may use. Built by the server from stored metadata, never rows. */
export interface ChatContext {
  tables: unknown[];
  memory: { kind: string; text: string; detail: string | null }[];
}

const contextParts = (c: ChatContext | null) =>
  c
    ? [
        c.tables.length ? untrusted('source_tables', JSON.stringify(c.tables)) : '',
        c.memory.length ? untrusted('project_memory', JSON.stringify(c.memory)) : '',
      ]
    : [];

export const intakeChatRequest = (
  projectGoal: string | null,
  messages: ChatMessage[],
  context: ChatContext | null = null
) =>
  [
    'Continue the interview.',
    projectGoal ? untrusted('sub_project_goal', projectGoal) : '',
    ...contextParts(context),
    untrusted('conversation', transcript(messages)),
  ]
    .filter(Boolean)
    .join('\n\n');

export const chatBriefRequest = (
  projectGoal: string | null,
  messages: ChatMessage[],
  context: ChatContext | null = null
) =>
  [
    'Create the Semantic Brief from this interview. candidateSources are the source tables plus tables the user mentioned.',
    projectGoal ? untrusted('sub_project_goal', projectGoal) : '',
    ...contextParts(context),
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
