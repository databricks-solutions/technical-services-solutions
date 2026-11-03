export type CheckStatus = 'pass' | 'warn' | 'fail';

export interface ReadinessCheck {
  id: string;
  label: string;
  status: CheckStatus;
  detail: string;
}

export interface Assessment {
  role: 'fact' | 'dimension' | 'unknown';
  score: number;
  summary: string;
  findings: string[];
}

export interface ReadinessReport {
  id: string;
  score: number | null;
  checks: ReadinessCheck[];
  assessment: Assessment | null;
  createdAt: string;
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
}

export interface ReadinessView {
  sources: SourceReadiness[];
  recommendations: Recommendation[];
}
