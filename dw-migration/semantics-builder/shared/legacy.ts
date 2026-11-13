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
  format: 'dbt' | 'lookml' | 'tabular' | 'tableau' | 'cognos' | 'microstrategy' | 'ssas';
  /** The draft metric view, or null when nothing could be converted. */
  yaml: string | null;
  fields: LegacyField[];
  sources: string[];
  /** Problems with the model as a whole, such as a semantic model that does not join. */
  issues: string[];
  /** SQL that the AI wrote for measures with no rule, by measure name. Create sends it back unchanged. */
  ai?: Record<string, string>;
}

/** The tools that the import reads, with the file extensions of each. Several files of one tool are read as one. */
export const LEGACY_TOOLS = [
  { id: 'dbt', label: 'dbt MetricFlow', exts: ['.yml', '.yaml', '.json'], multiple: false },
  { id: 'lookml', label: 'LookML', exts: ['.lkml'], multiple: true },
  { id: 'powerbi', label: 'Power BI', exts: ['.pbit', '.tmdl'], multiple: true },
  { id: 'tabular', label: 'SSAS Tabular', exts: ['.bim'], multiple: false },
  { id: 'tableau', label: 'Tableau', exts: ['.twb', '.tds', '.twbx', '.tdsx'], multiple: false },
  { id: 'cognos', label: 'Cognos', exts: ['.xml'], multiple: false },
  { id: 'microstrategy', label: 'MicroStrategy', exts: ['.json'], multiple: false },
  { id: 'ssas', label: 'SSAS Multidimensional', exts: ['.dsv', '.dim', '.cube', '.xmla'], multiple: true },
] as const;
export type LegacyTool = (typeof LEGACY_TOOLS)[number]['id'];
export const legacyTool = (id: LegacyTool) => LEGACY_TOOLS.find((t) => t.id === id)!;
/** True when the file name ends with an extension of the tool (or is the name of several joined files). */
export const fitsTool = (id: LegacyTool, fileName: string) => {
  const n = fileName.toLowerCase();
  const joined = { lookml: '.lkml', powerbi: '.tmdl', ssas: '.ssas' } as Partial<Record<LegacyTool, string>>;
  return legacyTool(id).exts.some((e) => n.endsWith(e)) || (!!joined[id] && n.endsWith(joined[id]));
};

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
  /** The tool that the user picked. Without it, the server finds the tool from the file name and content. */
  tool: z.enum(LEGACY_TOOLS.map((t) => t.id) as [LegacyTool, ...LegacyTool[]]).optional(),
  /** The AI SQL of the preview, sent back on create, so the sub-project gets what the user saw. */
  ai: z.record(z.string().max(255), z.string().max(2000)).optional(),
  /** Without it, the server returns the preview only. */
  create: z.boolean().default(false),
});
