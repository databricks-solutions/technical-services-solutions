import { z } from 'zod';
import type { TestCase, ValidationRun } from './designer';

export interface Review {
  id: string;
  projectId: string;
  parentId: string;
  /** Top-level project / sub-project. */
  project: string;
  subProject: string;
  version: number;
  target: string | null;
  reviewer: string;
  requestedBy: string;
  requestComment: string | null;
  status: 'pending' | 'approved' | 'rejected' | 'cancelled';
  decisionComment: string | null;
  decidedAt: string | null;
  createdAt: string;
}

/** What the reviewer sees, read-only. */
export interface ReviewDetail {
  review: Review;
  /** You are the reviewer and the review is pending. */
  canDecide: boolean;
  yaml: string;
  /** The view in Unity Catalog now. null when it does not exist or cannot be read. */
  ucYaml: string | null;
  statement: string | null;
  tests: TestCase[];
  validation: ValidationRun | null;
}

export interface ReviewList {
  toMe: Review[];
  byMe: Review[];
}

/** On the Promotion section: whether Promote needs approval, and the latest review of the sub-project. */
export interface ApprovalState {
  required: boolean;
  review: Review | null;
}

export const approvalSchema = z.object({ required: z.boolean() });
export const requestReviewSchema = z.object({
  reviewer: z.email().max(320),
  comment: z.string().trim().max(2000).optional(),
});
export const decisionSchema = z
  .object({ decision: z.enum(['approved', 'rejected']), comment: z.string().trim().max(2000).default('') })
  .refine((d) => d.decision === 'approved' || d.comment.length > 0, {
    message: 'Say why you reject it.',
    path: ['comment'],
  });
