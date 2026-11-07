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
