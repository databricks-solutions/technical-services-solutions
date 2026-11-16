import { ACCURACY_TARGET } from '../../shared/agent';
import type { Gate, GoldenView } from '../../shared/agent';

export interface SubFacts {
  projectId: string;
  name: string;
  view: string;
  version: number;
  tables: number;
  certified: number;
  /** The promoted version has an approved review. */
  approved: boolean;
  /** The latest finished benchmark run, or null. */
  run: { correct: number; questions: number; at: string } | null;
}

const pct = (c: number, n: number) => (n ? Math.round((100 * c) / n) : 0);

export function subGates(s: SubFacts): Gate[] {
  const accuracy = s.run ? pct(s.run.correct, s.run.questions) : 0;
  return [
    {
      id: 'certified',
      label: 'The tables are certified',
      pass: s.tables > 0 && s.certified === s.tables,
      detail: `${s.certified} of ${s.tables} tables have the tag system.certification_status = certified.`,
      fix: 'sources?tab=certification',
    },
    {
      id: 'approved',
      label: 'The promoted version is approved',
      pass: s.approved,
      detail: s.approved
        ? `A reviewer approved version ${s.version}.`
        : `Version ${s.version} has no approved review. Turn on Promote needs approval and ask a reviewer.`,
      fix: 'publish?section=promotion',
    },
    {
      id: 'promoted',
      label: 'The view is promoted',
      pass: true,
      detail: `Version ${s.version} is in Unity Catalog as ${s.view}.`,
      fix: null,
    },
    {
      id: 'accuracy',
      label: `Genie accuracy is ${ACCURACY_TARGET}% or more`,
      pass: !!s.run && s.run.questions > 0 && accuracy >= ACCURACY_TARGET,
      detail: s.run
        ? `${accuracy}% (${s.run.correct} of ${s.run.questions} benchmarks), on ${s.run.at.slice(0, 10)}.`
        : `No benchmark run on version ${s.version}. Run the benchmarks on the latest version, then promote that version.`,
      fix: 'optimize?tab=genie',
    },
  ];
}

/** Golden only with an up-to-date agent and every gate of every sub-project in it. */
export function golden(agent: { exists: boolean; current: boolean } | null, subs: SubFacts[]): GoldenView {
  const agentGate: Gate = {
    id: 'agent',
    label: 'The project Genie agent is up to date',
    pass: !!agent?.exists && agent.current,
    detail: !agent?.exists
      ? 'Create the Genie agent of the project.'
      : agent.current
        ? 'The agent has the settings of the promoted versions.'
        : 'Update the Genie agent.',
    fix: null,
  };
  const subProjects = subs.map((s) => ({ projectId: s.projectId, name: s.name, gates: subGates(s) }));
  return {
    golden: agentGate.pass && subProjects.length > 0 && subProjects.every((s) => s.gates.every((g) => g.pass)),
    agent: agentGate,
    subProjects,
  };
}
