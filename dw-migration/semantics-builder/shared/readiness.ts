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
  /** Brief version the coverage was mapped against. null when no brief was confirmed. */
  briefVersion?: number | null;
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

export interface FixColumn {
  name: string;
  type: string;
}

/** One editable row of a fix: a comment to write, or the columns of a key. */
export type FixRow =
  | {
      kind: 'comment';
      /** Index of the statement in the fix. */
      index: number;
      table: string;
      column: string | null;
      type: string | null;
      current: string;
      proposed: string;
    }
  | {
      kind: 'key';
      table: string;
      columns: string[];
      options: FixColumn[];
      /** The referenced table of a foreign key; null for a primary key. */
      references: string | null;
      refColumns: string[];
      refOptions: FixColumn[];
    };

/** The user's changes to a proposed fix. The server rebuilds the SQL from them. */
export interface FixEdits {
  /** Edited comment text by statement index; null keeps the proposal. */
  comments?: (string | null)[];
  /** Statement indexes of comments to leave out. */
  skip?: number[];
  /** The key columns, and for a foreign key the referenced columns, in order. */
  key?: { columns: string[]; refColumns?: string[] };
}

export interface Recommendation {
  id: string;
  sourceName: string | null;
  kind: 'table_comment' | 'column_comments' | 'primary_key' | 'foreign_key';
  title: string;
  rationale: string;
  statements: string[];
  /** The fix as rows the user can edit. */
  rows: FixRow[];
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

export interface PermissionCheck {
  id: string;
  group: 'warehouse' | 'sources' | 'sandbox' | 'fixes';
  label: string;
  /** warn: the check found no grant, but inherited or group grants can still allow it. */
  status: CheckStatus;
  detail: string;
  /** Statements a catalog or table owner can run to grant what is missing. Never run by the app. */
  grants: string[];
}

/** How selected tables relate before they are added: rule-based joins and groups, plus the AI view. */
export interface RelationCheck {
  links: Link[];
  /** Tables connected by joins, largest group first. More than one group means some tables do not join. */
  groups: string[][];
  ai: {
    summary: string;
    tables: { table: string; belongs: boolean; reason: string }[];
    suggestion: string;
  } | null;
  aiError: string | null;
}
