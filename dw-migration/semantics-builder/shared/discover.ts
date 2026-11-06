import { z } from 'zod';

export interface DiscoveredKpi {
  view: string;
  kind: 'metric_view' | 'sql_view';
  name: string;
  expr: string;
}

/** KPIs in two or more views with the same name or the same expression after normalization. */
export interface KpiGroup {
  kpis: DiscoveredKpi[];
  /** True when the same name has two or more different formulas. */
  conflict: boolean;
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
