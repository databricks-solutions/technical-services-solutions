import { z } from 'zod';

export interface Grant {
  principal: string;
  privilege: string;
}

export interface GovernView {
  target: string | null;
  owner: string | null;
  /** The signed-in user is the owner, or in the owner group. Only the owner can transfer or grant. */
  youOwn: boolean;
  /** A materialized metric view cannot change owner, and a group cannot own it. */
  materialized: boolean;
  grants: Grant[];
  problem: string | null;
}

export const GOVERN_ACTIONS = ['owner', 'grant', 'revoke'] as const;
export const governSchema = z.object({
  action: z.enum(GOVERN_ACTIONS),
  principal: z
    .string()
    .trim()
    .min(1)
    .max(255)
    .regex(/^[^`\r\n]+$/, 'A user email, a group name or a service principal id, without backticks.'),
});
export const governRunSchema = governSchema.extend({ statement: z.string().min(1).max(2000) });

/** A tag on the promoted view (column null) or on one of its fields. */
export interface ViewTag {
  column: string | null;
  name: string;
  value: string;
}

export interface TagsView {
  target: string | null;
  youOwn: boolean;
  /** The fields of the view in Unity Catalog, which can have their own tags. */
  columns: string[];
  tags: ViewTag[];
  problem: string | null;
}

/** Tags that most teams use on a published metric view. */
export const SUGGESTED_TAGS = ['domain', 'owner_team', 'pii', 'sensitivity'] as const;

export const tagSchema = z.object({
  column: z.string().trim().min(1).max(255).nullable(),
  name: z
    .string()
    .trim()
    .min(1)
    .max(255)
    .regex(/^[A-Za-z0-9_ ]+$/, 'Use letters, digits, spaces and underscores.'),
  /** Null removes the tag. */
  value: z.string().trim().max(255).nullable(),
});
export const tagRunSchema = tagSchema.extend({ statement: z.string().min(1).max(2000) });
