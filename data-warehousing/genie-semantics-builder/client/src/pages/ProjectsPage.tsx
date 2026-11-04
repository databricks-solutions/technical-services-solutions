import { useState } from 'react';
import { useNavigate } from 'react-router';
import {
  Button,
  Card,
  FormUI,
  Input,
  MetricCard,
  Modal,
  PlusIcon,
  SearchIcon,
  Tag,
  Typography,
} from '@databricks/design-system';
import type { NewProject, Project, ProjectSummary, SubProjectStage } from '../../../shared/brief';
import { api, useResource } from '../api';
import { DataState } from '../components/DataState';

export const STAGE: Record<
  SubProjectStage,
  { label: string; color: 'default' | 'lemon' | 'indigo' | 'teal'; module: string }
> = {
  intent: { label: 'Defining intent', color: 'default', module: 'intake' },
  sources: { label: 'Checking sources', color: 'lemon', module: 'sources' },
  design: { label: 'Designing', color: 'indigo', module: 'designer' },
  validated: { label: 'Validated', color: 'teal', module: 'designer' },
};

export const subPath = (parentId: string, id: string, module: string) => `/projects/${parentId}/sub/${id}/${module}`;

/** Name and goal only. Sources come later, from the guided intake. */
export function NewProjectModal({
  title,
  okText,
  endpoint,
  goalHint,
  onClose,
  onCreated,
}: {
  title: string;
  okText: string;
  endpoint: string;
  goalHint: string;
  onClose: () => void;
  onCreated: (p: Project) => void;
}) {
  const [form, setForm] = useState<NewProject>({ name: '' });
  const [error, setError] = useState<string>();
  const [saving, setSaving] = useState(false);

  const submit = () => {
    setSaving(true);
    setError(undefined);
    api<Project>(endpoint, form).then(onCreated, (err: unknown) => {
      setError((err as Error).message);
      setSaving(false);
    });
  };

  return (
    <Modal
      componentId="gsb.projects.new_modal"
      title={title}
      visible
      okText={okText}
      onOk={submit}
      okButtonProps={{ loading: saving, disabled: !form.name.trim() }}
      cancelText="Cancel"
      onCancel={onClose}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div>
          <FormUI.Label htmlFor="gsb-project-name" required>
            Name
          </FormUI.Label>
          <Input
            componentId="gsb.projects.name"
            id="gsb-project-name"
            value={form.name}
            maxLength={200}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          />
        </div>
        <div>
          <FormUI.Label htmlFor="gsb-project-description">Business goal</FormUI.Label>
          <FormUI.Hint>{goalHint}</FormUI.Hint>
          <Input.TextArea
            componentId="gsb.projects.description"
            id="gsb-project-description"
            value={form.description ?? ''}
            maxLength={4000}
            autoSize={{ minRows: 3, maxRows: 6 }}
            onChange={(e) => setForm((f) => ({ ...f, description: e.target.value || undefined }))}
          />
        </div>
        {error && <FormUI.Message type="error" message={error} />}
      </div>
    </Modal>
  );
}

function ProjectCard({ project }: { project: ProjectSummary }) {
  const navigate = useNavigate();
  const subs = project.subProjects;
  return (
    <Card componentId="gsb.projects.card" width="100%" onClick={() => void navigate(`/projects/${project.id}`)}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minHeight: 140 }}>
        <Typography.Title level={4} withoutMargins>
          {project.name}
        </Typography.Title>
        <Typography.Text color="secondary">{project.description ?? 'No business goal yet.'}</Typography.Text>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 'auto' }}>
          {subs.length ? (
            subs.slice(0, 4).map((s) => (
              <Tag key={s.id} componentId="gsb.projects.sub_tag" color={STAGE[s.stage].color}>
                {s.name}: {STAGE[s.stage].label}
              </Tag>
            ))
          ) : (
            <Typography.Text color="secondary">No sub-projects yet</Typography.Text>
          )}
          {subs.length > 4 && <Tag componentId="gsb.projects.more">+{subs.length - 4} more</Tag>}
        </div>
      </div>
    </Card>
  );
}

export function ProjectsPage() {
  const navigate = useNavigate();
  const projects = useResource<ProjectSummary[]>('/api/projects');
  const [creating, setCreating] = useState(false);
  const [filter, setFilter] = useState('');
  const list = projects.data ?? [];
  const needle = filter.trim().toLowerCase();
  const shown = list.filter((p) =>
    [p.name, p.description ?? '', ...p.subProjects.map((s) => s.name)].some((t) => t.toLowerCase().includes(needle))
  );
  const subs = list.flatMap((p) => p.subProjects);
  const newButton = (
    <Button componentId="gsb.projects.new" type="primary" icon={<PlusIcon />} onClick={() => setCreating(true)}>
      New project
    </Button>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16 }}>
        <Typography.Paragraph withoutMargins color="secondary" style={{ maxWidth: 720 }}>
          Design governed Unity Catalog metric views with an AI guide. A project is a business domain. Each sub-project
          builds one metric view, from intent to a validated design.
        </Typography.Paragraph>
        {newButton}
      </div>
      <DataState
        status={projects.status === 'ready' && !list.length ? 'empty' : projects.status}
        message={projects.error ?? 'Create a project for a business domain, such as Sales or Finance.'}
        emptyAction={newButton}
        onRetry={projects.reload}
      >
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 16 }}>
          <MetricCard componentId="gsb.projects.metric_projects" label="Projects" metric={String(list.length)} />
          <MetricCard componentId="gsb.projects.metric_subs" label="Sub-projects" metric={String(subs.length)} />
          <MetricCard
            componentId="gsb.projects.metric_validated"
            label="Validated metric views"
            metric={String(subs.filter((s) => s.stage === 'validated').length)}
            comparison={`of ${subs.length} sub-projects`}
          />
        </div>
        <Input
          componentId="gsb.projects.filter"
          aria-label="Search projects"
          placeholder="Search projects and sub-projects"
          prefix={<SearchIcon />}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          allowClear
          style={{ maxWidth: 400 }}
        />
        {shown.length ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 16 }}>
            {shown.map((p) => (
              <ProjectCard key={p.id} project={p} />
            ))}
          </div>
        ) : (
          <Typography.Text color="secondary">No project matches the search.</Typography.Text>
        )}
      </DataState>
      {creating && (
        <NewProjectModal
          title="New project"
          okText="Create project"
          endpoint="/api/projects"
          goalHint="What should this domain answer? For example: track revenue and margin by region and product."
          onClose={() => setCreating(false)}
          onCreated={(p) => void navigate(`/projects/${p.id}`)}
        />
      )}
    </div>
  );
}
