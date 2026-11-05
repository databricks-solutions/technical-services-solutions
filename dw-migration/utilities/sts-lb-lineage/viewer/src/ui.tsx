import { TableIcon, Tag, WorkflowsIcon } from '@databricks/design-system';

import type { LNode } from './data';

export const KindIcon = ({ kind }: { kind: LNode['kind'] }) =>
  kind === 'job' ? <WorkflowsIcon aria-hidden /> : <TableIcon aria-hidden />;

export const kindLabel = (k: LNode['kind']) => (k === 'job' ? 'Job' : 'Table');

const LEVEL_LABEL: Record<string, string> = {
  LOW: 'Low',
  MEDIUM: 'Medium',
  HIGH: 'High',
  COMPLEX: 'Complex',
  VERY_HIGH: 'Very high',
  UNKNOWN: 'Unknown',
};
export const levelLabel = (lv: string) => LEVEL_LABEL[lv] ?? lv;

const LEVEL_COLOR = { LOW: 'teal', MEDIUM: 'lemon', HIGH: 'coral', COMPLEX: 'coral', VERY_HIGH: 'pink' } as const;

/** Complexity tag: color plus text, never color alone. */
export const LevelTag = ({ level, count }: { level: string; count?: number }) => (
  <Tag componentId="sts-lb-lineage.complexity" color={LEVEL_COLOR[level as keyof typeof LEVEL_COLOR] ?? 'default'}>
    {count === undefined ? levelLabel(level) : `${levelLabel(level)}: ${count}`}
  </Tag>
);

/** One tag per used level, highest last, e.g. Low: 6  Medium: 4  High: 2. */
export const LevelMix = ({ counts }: { counts: Record<string, number> }) => (
  <span className="lbl-row">
    {['LOW', 'MEDIUM', 'HIGH', 'COMPLEX', 'VERY_HIGH', 'UNKNOWN']
      .filter((lv) => counts[lv])
      .map((lv) => (
        <LevelTag key={lv} level={lv} count={counts[lv]} />
      ))}
  </span>
);

const ROLE_LABEL: Record<string, string> = {
  source: 'Source',
  intermediate: 'Intermediate',
  terminal: 'Terminal output',
  orphan: 'Orphan',
  job: 'Job',
};
export const roleLabel = (r?: string) => (r ? ROLE_LABEL[r] ?? r : '-');

export const ROLE_HELP: Record<string, string> = {
  source: 'Read but never written by the scanned code. Ingestion scope: land these first.',
  intermediate: 'Written and read inside the estate.',
  terminal: 'Written but never read by the scanned code. Outputs for consumers, or dead-code candidates.',
  orphan: 'Referenced without a read or write relation.',
};

export const fmt = (n: number) => n.toLocaleString();

/** "1 table", "2 tables". */
export const plural = (n: number, word: string, many = `${word}s`) => `${n.toLocaleString()} ${n === 1 ? word : many}`;
