import { useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import {
  ArrowRightIcon,
  Button,
  DropdownMenu,
  OverflowIcon,
  PlusIcon,
  Table,
  TableCell,
  TableHeader,
  TableRow,
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
import { PageHeader } from '../components/PageHeader';
import { useTab } from '../useTab';

const TABS = ['subprojects', 'golden', 'agent', 'dictionary'] as const;

/** The sub-projects of a project as one table: a row each, with its step marks, and the next step as a button. */
function SubProjectTable({
  parentId,
  subs,
  onDelete,
}: {
  parentId: string;
  subs: SubProjectSummary[];
  onDelete: (id: string) => void;
}) {
  const navigate = useNavigate();
  return (
    <div style={{ overflowX: 'auto' }}>
      <Table aria-label="Sub-projects" style={{ minWidth: 960 }}>
        <TableRow isHeader>
          <TableHeader componentId="gsb.project.h_name" style={{ flex: 2.2 }}>
            Sub-project
          </TableHeader>
          <TableHeader componentId="gsb.project.h_stage" style={{ flex: 1 }}>
            Status
          </TableHeader>
          <TableHeader componentId="gsb.project.h_progress" style={{ flex: 1 }}>
            Progress
          </TableHeader>
          <TableHeader componentId="gsb.project.h_sources" style={{ flex: 0.6 }}>
            Sources
          </TableHeader>
          <TableHeader componentId="gsb.project.h_activity" style={{ flex: 1.2 }}>
            Last activity
          </TableHeader>
          <TableHeader componentId="gsb.project.h_actions" style={{ flex: 1.8 }}>
            Next step
          </TableHeader>
        </TableRow>
        {subs.map((sub) => {
          // Opening a sub-project starts on its overview; the Next button goes to the step that is due.
          const overview = subPath(parentId, sub.id, 'overview');
          const next = NEXT[sub.stage];
          return (
            <TableRow key={sub.id}>
              <TableCell multiline style={{ flex: 2.2 }}>
                <div style={{ display: 'flex', flexDirection: 'column' }}>
                  <Typography.Link
                    componentId="gsb.project.sub_open"
                    href={overview}
                    onClick={(e) => {
                      e.preventDefault();
                      void navigate(overview);
                    }}
                  >
                    {sub.name}
                  </Typography.Link>
                  {sub.description && (
                    <Typography.Text color="secondary" size="sm">
                      {sub.description}
                    </Typography.Text>
                  )}
                </div>
              </TableCell>
              <TableCell style={{ flex: 1 }}>
                <Tag componentId="gsb.project.sub_stage" color={STAGE[sub.stage].color}>
                  {STAGE[sub.stage].label}
                </Tag>
              </TableCell>
              <TableCell style={{ flex: 1 }} wrapContent={false}>
                <Journey stage={sub.stage} compact />
              </TableCell>
              <TableCell style={{ flex: 0.6 }}>{sub.sources}</TableCell>
              <TableCell style={{ flex: 1.2 }}>{new Date(sub.lastActivity).toLocaleString()}</TableCell>
              <TableCell style={{ flex: 1.8 }}>
                <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                  {/* The step text is the same on many rows, so it is a tooltip; the button names the next step. */}
                  <Button
                    componentId="gsb.project.sub_next"
                    size="small"
                    endIcon={<ArrowRightIcon />}
                    title={next.text}
                    onClick={() => void navigate(subPath(parentId, sub.id, next.module))}
                  >
                    {next.action}
                  </Button>
                  <Button
                    componentId="gsb.project.sub_delete"
                    type="tertiary"
                    size="small"
                    icon={<TrashIcon />}
                    aria-label={`Delete sub-project ${sub.name}`}
                    onClick={() => onDelete(sub.id)}
                  />
                </div>
              </TableCell>
            </TableRow>
          );
        })}
      </Table>
    </div>
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
          <PageHeader
            title={project.name}
            description={project.description ?? 'No business goal yet.'}
            actions={
              <>
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
              </>
            }
          />
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
                  <SubProjectTable
                    parentId={project.id}
                    subs={project.subProjects}
                    onDelete={(id) => setDeleting({ id, kind: 'sub-project' })}
                  />
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
