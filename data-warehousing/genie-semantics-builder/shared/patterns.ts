import { z } from 'zod';

const text = (max: number) => z.string().trim().min(1).max(max);

export const VIEW_PLACEHOLDER = '{{view}}';

/** pattern.yml in each folder of the library. */
export const patternMetaSchema = z.strictObject({
  title: text(80),
  category: text(60),
  scenario: text(2000),
  question: text(300),
  /** The columns a user must map to their own data in "Apply to my data". */
  roles: z.array(z.strictObject({ name: z.string().regex(/^[a-z][a-z0-9_]{0,40}$/), description: text(300) })).min(1),
  test: z.strictObject({ query: text(5000).refine((q) => q.includes(VIEW_PLACEHOLDER), 'must use {{view}}') }),
  minDbr: z
    .string()
    .regex(/^\d+\.\d+$/)
    .optional(),
});

/** expected.json, written by scripts/run-patterns.ts from a real run. */
export const expectedSchema = z.strictObject({
  columns: z.array(z.string()).min(1),
  rows: z.array(z.array(z.string().nullable())).max(50),
});

export type PatternMeta = z.infer<typeof patternMetaSchema>;
export type Expected = z.infer<typeof expectedSchema>;

export interface Pattern extends PatternMeta {
  slug: string;
  yaml: string;
  expected: Expected;
}
