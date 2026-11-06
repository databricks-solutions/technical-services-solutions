import { z } from 'zod';

export interface DiscoveredKpi {
  view: string;
  kind: 'metric_view' | 'sql_view';
  name: string;
  expr: string;
  /** The main table the KPI reads, lower case without quotes, when known. */
  source?: string;
}

/** KPIs in two or more views with the same name or the same expression after normalization. */
export interface KpiGroup {
  kpis: DiscoveredKpi[];
  /** True when the same name has two or more formulas on the same table, or on a table not known. */
  conflict: boolean;
  /** True when the same name has other formulas only because it reads other tables. */
  differentTables: boolean;
  /** The formula most views use. A metric view wins a tie. */
  canonical: DiscoveredKpi;
  /** The other views of the group, that the canonical view replaces. */
  replaces: string[];
}

export interface DiscoverResult {
  views: { fullName: string; kind: DiscoveredKpi['kind']; kpis: number }[];
  groups: KpiGroup[];
  problems: string[];
}

export const MAX_DISCOVER_SCHEMAS = 10;
export const discoverSchema = z.object({
  schemas: z
    .array(z.string().regex(/^[^\s.`]+\.[^\s.`]+$/, 'Use catalog.schema.'))
    .min(1)
    .max(MAX_DISCOVER_SCHEMAS),
});

/** A proposed definition, to store as a certified metric in a project dictionary. */
export const certifySchema = z.strictObject({
  name: z.string().trim().min(1).max(200),
  formula: z.string().trim().min(1).max(4000),
  source: z.string().trim().max(400).optional(),
  /** The other names of the KPI in the views. */
  synonyms: z.array(z.string().trim().min(1).max(200)).max(10),
  views: z.number().int().min(1).max(500),
});
