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
  format: 'dbt';
  /** The draft metric view, or null when nothing could be converted. */
  yaml: string | null;
  fields: LegacyField[];
  sources: string[];
  /** Problems with the model as a whole, such as a semantic model that does not join. */
  issues: string[];
}

// The JSON body limit of the server is 1 MB, and quotes in the file grow when they are sent as JSON.
export const MAX_LEGACY_BYTES = 800_000;

export const legacyBody = z.object({
  fileName: z.string().trim().min(1).max(255),
  content: z.string().min(1).max(MAX_LEGACY_BYTES),
  /** catalog.schema of the dbt models, for `ref('model')` in YAML files. The manifest has the real tables. */
  schema: z
    .string()
    .trim()
    .regex(/^[^\s.`]+\.[^\s.`]+$/, 'Type catalog.schema.')
    .optional(),
  subProject: z.string().trim().min(1).max(200),
  /** Without it, the server returns the preview only. */
  create: z.boolean().default(false),
});
