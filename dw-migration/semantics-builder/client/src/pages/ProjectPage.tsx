import { useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import {
  ArrowRightIcon,
  Button,
  Card,
  DropdownMenu,
  OverflowIcon,
  PlusIcon,
  TrashIcon,
  Tag,
  Typography,
} from '@databricks/design-system';
import type { ProjectSummary, SubProjectSummary } from '../../../shared/brief';
import { Journey, NEXT, STAGE } from '../journey';
import { PROJECTS_CHANGED, useResource } from '../api';
import { DataState } from '../components/DataState';
import { AgentPanel } from '../components/AgentPanel';
import { DictionaryPanel } from '../components/DictionaryPanel';
import { DeleteProjectModal } from '../components/DeleteProjectModal';
import { NewProjectModal, subPath } from './ProjectsPage';

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
  // Opening a sub-project starts on its overview; the Next button goes to the step that is due.
  const overview = subPath(parentId, sub.id, 'overview');
  const open = () => void navigate(overview);
  const next = NEXT[sub.stage];
  const goNext = () => void navigate(subPath(parentId, sub.id, next.module));
  return (
    <Card componentId="gsb.project.sub_card" width="100%" onClick={open}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
          <div>
            <Typography.Title level={4} withoutMargins>
              <Typography.Link
                componentId="gsb.project.sub_open"
                href={overview}
                onClick={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  open();
                }}
              >
                {sub.name}
              </Typography.Link>
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
              {newButton}
              <DropdownMenu.Root modal={false}>
                <DropdownMenu.Trigger asChild>
                  <Button componentId="gsb.project.more" icon={<OverflowIcon />} aria-label="More actions" />
                </DropdownMenu.Trigger>
                <DropdownMenu.Content align="end">
                  <DropdownMenu.Item
                    componentId="gsb.project.delete"
                    danger
                    onClick={() => setDeleting({ id: project.id, kind: 'project' })}
                  >
                    <DropdownMenu.IconWrapper>
                      <TrashIcon />
                    </DropdownMenu.IconWrapper>
                    Delete project
                  </DropdownMenu.Item>
                </DropdownMenu.Content>
              </DropdownMenu.Root>
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
              emptyTitle="No sub-projects yet"
              message="A sub-project builds one metric view, for example Revenue or Returns. The AI guides you from intent to a validated design."
              emptyAction={newButton}
            />
          )}
          <AgentPanel projectId={project.id} />
          <DictionaryPanel projectId={project.id} />
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
