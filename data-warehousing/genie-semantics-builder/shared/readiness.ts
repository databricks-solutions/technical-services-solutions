export type CheckStatus = 'pass' | 'warn' | 'fail';

export interface ReadinessCheck {
  id: string;
  label: string;
  status: CheckStatus;
  detail: string;
}

export interface Assessment {
  role: 'fact' | 'dimension' | 'unknown';
  /** Business entity the table holds, such as Customer or Order line. */
  entity?: string;
  /** Brief measures and dimensions this table can source, by column. */
  coverage?: { item: string; column: string }[];
  score: number;
  summary: string;
  findings: string[];
}

export interface ReadinessReport {
  id: string;
  /** Rule-based semantic score from the areas. null for reports made before scoring existed. */
  score: number | null;
  areas: AreaScore[];
  checks: ReadinessCheck[];
  assessment: Assessment | null;
  createdAt: string;
}

export interface AreaScore {
  id: 'documentation' | 'keys' | 'types' | 'naming' | 'coverage';
  label: string;
  weight: number;
  score: number;
  detail: string;
}

/** A join between two tables: declared as a foreign key, or suggested by the key names. */
export interface Link {
  from: string;
  column: string;
  to: string;
  refColumn: string;
}

export interface Ontology {
  entities: { table: string; entity: string; role: Assessment['role']; score: number | null }[];
  links: (Link & { declared: boolean })[];
  /** Brief measures and dimensions with no source column, and tables with no join. */
  unmapped: string[];
  unlinked: string[];
}

export interface RelatedTable {
  table: string;
  reasons: string[];
}

export interface SourceReadiness {
  sourceId: string;
  fullName: string;
  role: Assessment['role'];
  report: ReadinessReport | null;
}

export type RecommendationStatus = 'proposed' | 'approved' | 'applied' | 'rejected' | 'failed';

export interface Recommendation {
  id: string;
  sourceName: string | null;
  kind: 'table_comment' | 'column_comments' | 'primary_key' | 'foreign_key';
  title: string;
  rationale: string;
  statements: string[];
  status: RecommendationStatus;
  error: string | null;
  decidedBy: string | null;
  decidedAt: string | null;
  /** Points the sub-project score gains when this fix is applied. */
  scoreGain: number;
}

export interface ReadinessView {
  score: { score: number; areas: AreaScore[] } | null;
  ontology: Ontology;
  sources: SourceReadiness[];
  recommendations: Recommendation[];
}
