import { z } from 'zod';

/** A sub-project with a promoted view: it can be part of the project Genie agent. */
export interface AgentCandidate {
  projectId: string;
  name: string;
  view: string;
  version: number;
  /** Changes kept by Optimize with benchmarks. */
  kept: number;
}

/** The production Genie agent of a top-level project: one Genie space on promoted views of its sub-projects. */
export interface AgentView {
  candidates: AgentCandidate[];
  agent: {
    spaceId: string;
    subProjects: string[];
    createdAt: string;
    updatedAt: string;
    /** The agent has the settings of the promoted versions and the kept changes. */
    current: boolean;
  } | null;
}

// No quote, backslash or dollar sign, so the name is safe inside the shell command.
const principal = z.object({
  kind: z.enum(['user', 'group']),
  name: z
    .string()
    .trim()
    .min(1)
    .max(320)
    .regex(/^[^'"`\\$]+$/, 'A name cannot hold quotes, a backslash or a dollar sign.'),
});
export type Principal = z.infer<typeof principal>;
export const agentBody = z.object({
  subProjects: z.array(z.uuid()).min(1).max(20),
  /** The settings the user examined. Absent: the server returns them without a change. */
  config: z.string().min(1).max(3_500_000).optional(),
});
export const accessBody = z.object({
  principals: z
    .array(principal)
    .min(1)
    .max(50)
    .refine((ps) => ps.every((p) => p.kind === 'group' || z.email().safeParse(p.name).success), {
      message: 'A user is named by email.',
    }),
});

/** The body of the permissions PATCH: CAN RUN for each principal, sorted, so the examined text can be compared. */
export function accessRequest(principals: Principal[]): string {
  const unique = [...new Map(principals.map((p) => [`${p.kind}:${p.name.toLowerCase()}`, p])).values()].sort((a, b) =>
    `${a.kind}:${a.name}`.localeCompare(`${b.kind}:${b.name}`)
  );
  return JSON.stringify(
    {
      access_control_list: unique.map((p) => ({
        [p.kind === 'user' ? 'user_name' : 'group_name']: p.name,
        permission_level: 'CAN_RUN',
      })),
    },
    null,
    2
  );
}

/**
 * Apps cannot get the access-management scope, so the app cannot change who can use a Genie space. The author runs
 * this command as themselves, with the Databricks CLI.
 */
export const accessCommand = (spaceId: string, principals: Principal[]) =>
  `databricks permissions update genie ${spaceId} --json '${JSON.stringify(JSON.parse(accessRequest(principals)))}'`;
