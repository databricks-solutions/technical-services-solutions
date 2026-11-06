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
}
