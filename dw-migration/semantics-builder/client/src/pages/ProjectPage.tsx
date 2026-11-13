import { useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import {
  ArrowRightIcon,
  Button,
  Card,
  DropdownMenu,
  OverflowIcon,
  PlusIcon,
  Tabs,
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
import { GoldenPanel } from '../components/GoldenPanel';
import { DeleteProjectModal } from '../components/DeleteProjectModal';
import { LegacyImportModal } from '../components/LegacyImportModal';
import { NewProjectModal, subPath } from './ProjectsPage';
import { useTab } from '../useTab';

const TABS = ['subprojects', 'golden', 'agent', 'dictionary'] as const;

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
  const [importingLegacy, setImportingLegacy] = useState(false);
  const [deleting, setDeleting] = useState<{ id: string; kind: 'project' | 'sub-project' }>();
  const project = projects.data?.find((p) => p.id === parentId);
  const status = projects.status === 'ready' && !project ? 'error' : projects.status;
  // One tab at a time, so the page does not scroll through every section.
  const [tab, setTab] = useTab(TABS, 'subprojects');
  const newButton = (
    <Button componentId="gsb.project.new_sub" type="primary" icon={<PlusIcon />} onClick={() => setCreating(true)}>
      New sub-project
    </Button>
  );
  const newMenu = (
    <DropdownMenu.Root modal={false}>
      <DropdownMenu.Trigger asChild>
        <Button componentId="gsb.project.new" type="primary" icon={<PlusIcon />}>
          New
        </Button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Content align="end">
        <DropdownMenu.Item componentId="gsb.project.new_sub_item" onClick={() => setCreating(true)}>
          New sub-project
        </DropdownMenu.Item>
        <DropdownMenu.Item componentId="gsb.project.new_agent" onClick={() => setTab('agent')}>
          New Genie agent
        </DropdownMenu.Item>
        <DropdownMenu.Item componentId="gsb.project.new_dictionary" onClick={() => setTab('dictionary')}>
          Metric dictionary
        </DropdownMenu.Item>
        <DropdownMenu.Item componentId="gsb.project.import_legacy" onClick={() => setImportingLegacy(true)}>
          Import a legacy model
        </DropdownMenu.Item>
      </DropdownMenu.Content>
    </DropdownMenu.Root>
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
              {newMenu}
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
          <Tabs.Root componentId="gsb.project.tabs" value={tab} onValueChange={setTab}>
            <Tabs.List>
              <Tabs.Trigger value="subprojects">Sub-projects ({project.subProjects.length})</Tabs.Trigger>
              <Tabs.Trigger value="golden">Golden project</Tabs.Trigger>
              <Tabs.Trigger value="agent">Genie agent</Tabs.Trigger>
              <Tabs.Trigger value="dictionary">Metric dictionary</Tabs.Trigger>
            </Tabs.List>
            <Tabs.Content value="subprojects">
              <div style={{ paddingTop: 16 }}>
                {project.subProjects.length ? (
                  <div
                    style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(380px, 1fr))', gap: 16 }}
                  >
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
              </div>
            </Tabs.Content>
            <Tabs.Content value="golden">
              <div style={{ paddingTop: 16 }}>
                <GoldenPanel projectId={project.id} />
              </div>
            </Tabs.Content>
            <Tabs.Content value="agent">
              <div style={{ paddingTop: 16 }}>
                <AgentPanel projectId={project.id} />
              </div>
            </Tabs.Content>
            <Tabs.Content value="dictionary">
              <div style={{ paddingTop: 16 }}>
                <DictionaryPanel projectId={project.id} />
              </div>
            </Tabs.Content>
          </Tabs.Root>
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
          {importingLegacy && <LegacyImportModal projectId={project.id} onClose={() => setImportingLegacy(false)} />}
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
