import { z } from 'zod';

export interface Promotion {
  id: string;
  version: number;
  target: string;
  status: 'running' | 'succeeded' | 'failed';
  error: string | null;
  createdBy: string;
  createdAt: string;
}

export interface PromotionPlan {
  version: number;
  statement: string;
  /** The target view exists in Unity Catalog. */
  exists: boolean;
  /** The view in UC has a YAML that no version of this design has: someone changed it outside the app. */
  changedOutside: boolean;
  ucYaml: string | null;
}

export interface PromotionView {
  target: string | null;
  promotions: Promotion[];
  plan: PromotionPlan | null;
  /** Why the latest version cannot be promoted now. */
  problem: string | null;
}

export const targetSchema = z.object({ fullName: z.string().trim().min(5).max(800) });
export const promoteSchema = z.object({
  version: z.number().int().positive(),
  statement: z.string().min(1).max(200_000),
  overwrite: z.boolean(),
});

/** One sub-project with a design, for the Metric views library. */
export interface LibraryRow {
  projectId: string;
  parentId: string;
  project: string;
  subProject: string;
  name: string;
  target: string | null;
  latest: { version: number; status: 'draft' | 'validated' };
  promoted: { version: number; by: string; at: string } | null;
  /** The sandbox view of the last passed validation. It can be dropped since. */
  sandboxView: string | null;
  /** From the last drift check. null when the view was never checked. */
  health: { status: 'ok' | 'warning' | 'error'; at: string } | null;
}

/** A metric view in Unity Catalog that the app does not manage for this user yet. */
export interface AdoptableView {
  fullName: string;
  owner: string | null;
  lastAltered: string | null;
  comment: string | null;
  /** True when another user's sub-project already manages it. */
  managedByOther: boolean;
}

export type ConsumerKind =
  | 'genie_space'
  | 'dashboard'
  | 'alert'
  | 'app'
  | 'job'
  | 'pipeline'
  | 'notebook'
  | 'query'
  | 'adhoc';

/** One consumer of the view in Unity Catalog, from lineage. Counts only: no user names, no query text. */
export interface Consumer {
  kind: ConsumerKind;
  /** null for ad hoc queries (SQL editor, API, BI tools). */
  id: string | null;
  users: number;
  queries: number;
  lastUsed: string;
  /** The removed or changed fields that its queries name. */
  uses: string[];
}

export interface FieldChanges {
  removed: string[];
  renamed: { from: string; to: string }[];
  /** Same name, new expression. */
  changed: string[];
  added: string[];
  filterChanged: boolean;
}

export interface Impact {
  /** null when the view is not in Unity Catalog yet. */
  changes: FieldChanges | null;
  /** null when lineage cannot be read, with the reason in error. */
  consumers: Consumer[] | null;
  error: string | null;
  days: number;
}
