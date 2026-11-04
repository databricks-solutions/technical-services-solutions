import { useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import {
  ArrowRightIcon,
  Button,
  Card,
  CheckCircleFillIcon,
  CircleIcon,
  CircleOutlineIcon,
  PlusIcon,
  TrashIcon,
  Tag,
  Typography,
} from '@databricks/design-system';
import type { ProjectSummary, SubProjectStage, SubProjectSummary } from '../../../shared/brief';
import { PROJECTS_CHANGED, useResource } from '../api';
import { DataState } from '../components/DataState';
import { DeleteProjectModal } from '../components/DeleteProjectModal';
import { NewProjectModal, STAGE, subPath } from './ProjectsPage';

const JOURNEY: { stage: SubProjectStage; label: string }[] = [
  { stage: 'sources', label: 'Sources' },
  { stage: 'intent', label: 'Goal' },
  { stage: 'design', label: 'Design' },
  { stage: 'validated', label: 'Validated' },
];

const NEXT: Record<SubProjectStage, { text: string; action: string }> = {
  sources: { text: 'Choose the tables to model, then check and fix them.', action: 'Choose sources' },
  intent: { text: 'See what the AI suggests from your tables, then confirm the brief.', action: 'Define the goal' },
  design: { text: 'Design the metric view and validate it against the data.', action: 'Open designer' },
  validated: { text: 'The metric view passed validation. Review or refine it.', action: 'Open designer' },
};

function Journey({ stage }: { stage: SubProjectStage }) {
  const at = JOURNEY.findIndex((j) => j.stage === stage);
  return (
    <ol
      aria-label="Progress"
      style={{ display: 'flex', gap: 16, flexWrap: 'wrap', margin: 0, padding: 0, listStyle: 'none' }}
    >
      {JOURNEY.map((j, i) => {
        const done = i < at || stage === 'validated';
        const current = i === at && !done;
        return (
          <li
            key={j.stage}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 4,
              color: done
                ? 'var(--db-alert-icon-color-success)'
                : current
                  ? 'var(--db-accent-text)'
                  : 'var(--db-text-subtle)',
              fontWeight: current ? 600 : undefined,
            }}
          >
            {done ? <CheckCircleFillIcon /> : current ? <CircleIcon /> : <CircleOutlineIcon />}
            <span>{j.label}</span>
            <span style={SR_ONLY}>{done ? ', done' : current ? ', current step' : ', not started'}</span>
          </li>
        );
      })}
    </ol>
  );
}

const SR_ONLY = {
  position: 'absolute',
  width: 1,
  height: 1,
  overflow: 'hidden',
  clip: 'rect(0 0 0 0)',
  whiteSpace: 'nowrap',
} as const;

function SubProjectCard({
  parentId,
  sub,
  onDelete,
}: {
  parentId: string;
  sub: SubProjectSummary;
  onDelete: () => void;
}) {
  const navigate = useNavigate();
  // Opening a sub-project starts on its sources; the Next button goes to the step that is due.
  const open = () => void navigate(subPath(parentId, sub.id, 'sources'));
  const goNext = () => void navigate(subPath(parentId, sub.id, STAGE[sub.stage].module));
  const next = NEXT[sub.stage];
  return (
    <Card componentId="gsb.project.sub_card" width="100%" onClick={open}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
          <div>
            <Typography.Title level={4} withoutMargins>
              {sub.name}
            </Typography.Title>
            <Typography.Text color="secondary">{sub.description ?? 'No goal yet.'}</Typography.Text>
          </div>
          <Tag componentId="gsb.project.sub_stage" color={STAGE[sub.stage].color}>
            {STAGE[sub.stage].label}
          </Tag>
        </div>
        <Journey stage={sub.stage} />
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 12,
            padding: 12,
            borderRadius: 8,
            background: 'var(--db-surface-subtle)',
          }}
        >
          <div>
            <Typography.Text bold>Next: </Typography.Text>
            <Typography.Text>{next.text}</Typography.Text>
          </div>
          <Button
            componentId="gsb.project.sub_next"
            type="primary"
            size="small"
            endIcon={<ArrowRightIcon />}
            onClick={(e) => {
              e.stopPropagation();
              goNext();
            }}
          >
            {next.action}
          </Button>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
          <Typography.Text color="secondary" size="sm">
            {sub.sources} source{sub.sources === 1 ? '' : 's'} - last activity{' '}
            {new Date(sub.lastActivity).toLocaleString()}
          </Typography.Text>
          <Button
            componentId="gsb.project.sub_delete"
            type="tertiary"
            size="small"
            icon={<TrashIcon />}
            aria-label={`Delete sub-project ${sub.name}`}
            onClick={(e) => {
              e.stopPropagation();
              onDelete();
            }}
          >
            Delete
          </Button>
        </div>
      </div>
    </Card>
  );
}

export function ProjectPage() {
  const { parentId = '' } = useParams();
  const navigate = useNavigate();
  const projects = useResource<ProjectSummary[]>('/api/projects');
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<{ id: string; kind: 'project' | 'sub-project' }>();
  const project = projects.data?.find((p) => p.id === parentId);
  const status = projects.status === 'ready' && !project ? 'error' : projects.status;
  const newButton = (
    <Button componentId="gsb.project.new_sub" type="primary" icon={<PlusIcon />} onClick={() => setCreating(true)}>
      New sub-project
    </Button>
  );

  return (
    <DataState status={status} message={projects.error ?? 'Project not found.'} onRetry={projects.reload}>
      {project && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16 }}>
            <div>
              <Typography.Title level={2} withoutMargins>
                {project.name}
              </Typography.Title>
              <Typography.Text color="secondary">{project.description ?? 'No business goal yet.'}</Typography.Text>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <Button
                componentId="gsb.project.delete"
                danger
                icon={<TrashIcon />}
                onClick={() => setDeleting({ id: project.id, kind: 'project' })}
              >
                Delete project
              </Button>
              {newButton}
            </div>
          </div>
          {project.subProjects.length ? (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(380px, 1fr))', gap: 16 }}>
              {project.subProjects.map((s) => (
                <SubProjectCard
                  key={s.id}
                  parentId={project.id}
                  sub={s}
                  onDelete={() => setDeleting({ id: s.id, kind: 'sub-project' })}
                />
              ))}
            </div>
          ) : (
            <DataState
              status="empty"
              message="A sub-project builds one metric view, for example Revenue or Returns. The AI guides you from intent to a validated design."
              emptyAction={newButton}
            />
          )}
          {deleting && (
            <DeleteProjectModal
              projectId={deleting.id}
              kind={deleting.kind}
              onClose={() => setDeleting(undefined)}
              onDeleted={() => {
                setDeleting(undefined);
                if (deleting.kind === 'project') void navigate('/');
                else {
                  projects.reload();
                  window.dispatchEvent(new Event(PROJECTS_CHANGED));
                }
              }}
            />
          )}
          {creating && (
            <NewProjectModal
              title="New sub-project"
              okText="Create sub-project"
              endpoint={`/api/projects/${project.id}/subprojects`}
              goalHint="Optional. If you do not know yet, choose the tables first and the AI suggests what you can build."
              onClose={() => setCreating(false)}
              onCreated={(s) => void navigate(subPath(project.id, s.id, 'sources'))}
            />
          )}
        </div>
      )}
    </DataState>
  );
}
