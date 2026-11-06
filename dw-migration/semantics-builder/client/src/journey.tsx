import { CheckCircleFillIcon, CircleIcon, CircleOutlineIcon, LockIcon } from '@databricks/design-system';
import type { SubProjectStage } from '../../shared/brief';

const ORDER: SubProjectStage[] = ['sources', 'intent', 'design', 'validated', 'promoted'];
const at = (s: SubProjectStage) => ORDER.indexOf(s);

export type TabMark = 'done' | 'current' | 'locked' | 'open';

/** The tabs of a sub-project, in the order of the work. One name per module, used on every screen. */
export const MODULES = [
  { slug: 'overview', label: 'Overview', hint: 'Progress and the next step.' },
  {
    slug: 'sources',
    label: 'Sources & Readiness',
    hint: 'Pick the tables, check them, and fix their descriptions and keys.',
  },
  { slug: 'intake', label: 'Intent & Context', hint: 'The goal, questions, measures and dimensions.' },
  { slug: 'designer', label: 'Metric Designer', hint: 'Design the metric view, test it, and validate it.' },
  { slug: 'optimize', label: 'Optimize', hint: 'Optional: best practices, speed, cost, and a test with Genie.' },
  { slug: 'publish', label: 'Publish', hint: 'Put the view in Unity Catalog, set access, and check drift.' },
] as const;
export type ModuleSlug = (typeof MODULES)[number]['slug'];

export const markOf = (slug: ModuleSlug, stage: SubProjectStage): TabMark => {
  const s = at(stage);
  switch (slug) {
    case 'sources':
      return s > at('sources') ? 'done' : 'current';
    case 'intake':
      return s > at('intent') ? 'done' : s === at('intent') ? 'current' : 'open';
    case 'designer':
      return s >= at('validated') ? 'done' : s === at('design') ? 'current' : 'open';
    case 'optimize':
      return s >= at('validated') ? 'open' : 'locked';
    case 'publish':
      return s === at('promoted') ? 'done' : s === at('validated') ? 'current' : 'locked';
    default:
      return 'open';
  }
};

export function Mark({ mark }: { mark: TabMark }) {
  const icon = { done: <CheckCircleFillIcon />, current: <CircleIcon />, locked: <LockIcon />, open: null }[mark];
  const color = {
    done: 'var(--db-alert-icon-color-success)',
    current: 'var(--db-accent-text)',
    locked: 'var(--db-text-subtle)',
    open: undefined,
  }[mark];
  return icon && <span style={{ color, display: 'inline-flex' }}>{icon}</span>;
}

export const MARK_TEXT: Record<TabMark, string> = {
  done: ', done',
  current: ', next step',
  locked: ', needs a validated design',
  open: '',
};

/** The stage tag of a sub-project. */
export const STAGE: Record<
  SubProjectStage,
  { label: string; color: 'default' | 'lemon' | 'indigo' | 'teal' | 'turquoise' }
> = {
  sources: { label: 'Sources & Readiness', color: 'default' },
  intent: { label: 'Intent & Context', color: 'lemon' },
  design: { label: 'Metric Designer', color: 'indigo' },
  validated: { label: 'Validated', color: 'teal' },
  promoted: { label: 'In Unity Catalog', color: 'turquoise' },
};

/** The next step of a sub-project: why, the button text, and the tab it opens. */
export const NEXT: Record<SubProjectStage, { text: string; action: string; module: ModuleSlug }> = {
  sources: {
    text: 'Choose the tables to model, then check and fix them.',
    action: 'Open Sources & Readiness',
    module: 'sources',
  },
  intent: {
    text: 'See what the AI suggests from your tables, then confirm the brief.',
    action: 'Open Intent & Context',
    module: 'intake',
  },
  design: {
    text: 'Design the metric view and validate it against the data.',
    action: 'Open Metric Designer',
    module: 'designer',
  },
  validated: {
    text: 'The view passed validation. Optimize it if you want, then publish it to Unity Catalog.',
    action: 'Open Publish',
    module: 'publish',
  },
  promoted: {
    text: 'The view is in Unity Catalog. Set who can read it, and check drift from time to time.',
    action: 'Open Publish',
    module: 'publish',
  },
};

export const SR_ONLY = {
  position: 'absolute',
  width: 1,
  height: 1,
  overflow: 'hidden',
  clip: 'rect(0 0 0 0)',
  whiteSpace: 'nowrap',
} as const;

/** The modules as a progress list with a mark each. */
export function Journey({ stage }: { stage: SubProjectStage }) {
  const steps = MODULES.filter((m) => m.slug !== 'overview');
  return (
    <ol
      aria-label="Progress"
      style={{ display: 'flex', gap: 16, flexWrap: 'wrap', margin: 0, padding: 0, listStyle: 'none' }}
    >
      {steps.map((m) => {
        const mark = markOf(m.slug, stage);
        return (
          <li
            key={m.slug}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 4,
              color:
                mark === 'done'
                  ? 'var(--db-alert-icon-color-success)'
                  : mark === 'current'
                    ? 'var(--db-accent-text)'
                    : 'var(--db-text-subtle)',
              fontWeight: mark === 'current' ? 600 : undefined,
            }}
          >
            {mark === 'open' ? <CircleOutlineIcon /> : <Mark mark={mark} />}
            <span>{m.label}</span>
            <span style={SR_ONLY}>{MARK_TEXT[mark] || ', not started'}</span>
          </li>
        );
      })}
    </ol>
  );
}
