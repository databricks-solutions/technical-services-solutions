/** One test of the promoted view, run as one person. No result values, only the shape of the answer. */
export interface AccessResult {
  name: string;
  status: 'passed' | 'failed' | 'error';
  rows: number;
  detail: string;
}

export interface AccessRun {
  runBy: string;
  /** The run of the sub-project owner, which the other runs compare with. */
  isOwner: boolean;
  version: number;
  results: AccessResult[];
  createdAt: string;
}

/** What a test shows for another person, compared with the owner run. */
export type AccessDifference = 'same' | 'fewer_rows' | 'more_rows' | 'other_value' | 'fails' | 'no_owner_run';

export interface AccessView {
  target: string | null;
  version: number | null;
  tests: number;
  /** Latest run of each person on the promoted version, the owner first. */
  runs: AccessRun[];
  problem: string | null;
}

/** How one test of another person differs from the same test of the owner. */
export function accessDifference(owner: AccessResult | undefined, other: AccessResult): AccessDifference {
  if (other.status === 'error') return 'fails';
  if (!owner) return 'no_owner_run';
  if (other.rows < owner.rows) return 'fewer_rows';
  if (other.rows > owner.rows) return 'more_rows';
  // Same row count: an expected value test that passes for the owner and not here sees other numbers.
  return owner.status === 'passed' && other.status !== 'passed' ? 'other_value' : 'same';
}
