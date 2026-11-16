/** How people used the fields of the promoted view, from Unity Catalog lineage. Counts only, never names or SQL. */
export interface FieldUsage {
  name: string;
  kind: 'dimension' | 'measure';
  /** Distinct queries that read the field in the period. */
  queries: number;
  users: number;
  lastUsed: string | null;
  /** Other measures that use this measure with MEASURE(), so it cannot go even if nobody reads it. */
  usedBy: string[];
}

export interface UsageView {
  target: string | null;
  version: number | null;
  days: number;
  /** Queries and users of the whole view in the period. */
  totals: { queries: number; users: number } | null;
  fields: FieldUsage[];
  error: string | null;
}
