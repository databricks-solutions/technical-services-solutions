import type { ReadinessCheck } from './readiness';
import type { Review } from './review';

/** The Unity Catalog governed tag the app sets on certified tables. */
export const CERT_TAG = 'system.certification_status';

export interface DataChecks {
  checks: ReadinessCheck[];
  checkedAt: string;
  checkedBy: string;
}

/** One table as the reviewer sees it: checks and descriptions only, never a value of the data. */
export interface CertTableSnapshot {
  fullName: string;
  comment: string;
  columns: { name: string; type: string; comment: string }[];
  readinessScore: number | null;
  readiness: ReadinessCheck[];
  data: DataChecks;
}

export interface CertSnapshot {
  tables: CertTableSnapshot[];
}

export interface CertTable {
  sourceId: string;
  fullName: string;
  readinessScore: number | null;
  data: DataChecks | null;
  /** The tag value in Unity Catalog now, such as certified. null when not set. */
  status: string | null;
}

export interface CertificationView {
  tables: CertTable[];
  /** Why the tag values could not be read, or null. */
  statusError: string | null;
  /** The latest data review of the sub-project. */
  review: Review | null;
  /** The tables changed since the latest review was asked. */
  changed: boolean;
  /** The SQL that sets the tag, when the latest review is approved and the tables did not change. */
  statements: string[];
}
