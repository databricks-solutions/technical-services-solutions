import { z } from 'zod';

/** How a field of a legacy model came over: converted by rules, converted but to check, or left for a person. */
export type FieldStatus = 'converted' | 'review' | 'manual';

export interface LegacyField {
  /** The name in the metric view. */
  name: string;
  kind: 'measure' | 'dimension';
  /** The definition in the legacy model, as it was. */
  source: string;
  status: FieldStatus;
  note: string;
}

export interface LegacyPreview {
  format: 'dbt' | 'lookml' | 'tabular' | 'tableau' | 'cognos' | 'microstrategy';
  /** The draft metric view, or null when nothing could be converted. */
  yaml: string | null;
  fields: LegacyField[];
  sources: string[];
  /** Problems with the model as a whole, such as a semantic model that does not join. */
  issues: string[];
  /** SQL that the AI wrote for measures with no rule, by measure name. Create sends it back unchanged. */
  ai?: Record<string, string>;
}

// The JSON body limit of the server is 12 MB; quotes in a text file grow when they are sent as JSON.
export const MAX_LEGACY_BYTES = 10_000_000;

export const legacyBody = z.object({
  fileName: z.string().trim().min(1).max(255),
  content: z.string().min(1).max(MAX_LEGACY_BYTES),
  /** catalog.schema of the dbt models, for `ref('model')` in YAML files. The manifest has the real tables. */
  schema: z
    .string()
    .trim()
    .regex(/^[^\s.`]+\.[^\s.`]+$/, 'Type catalog.schema.')
    .optional(),
  /** base64 for a binary file such as a .pbit template. */
  encoding: z.enum(['text', 'base64']).default('text'),
  subProject: z.string().trim().min(1).max(200),
  /** The AI SQL of the preview, sent back on create, so the sub-project gets what the user saw. */
  ai: z.record(z.string().max(255), z.string().max(2000)).optional(),
  /** Without it, the server returns the preview only. */
  create: z.boolean().default(false),
});
