import { useState } from 'react';
import { useNavigate } from 'react-router';
import {
  Alert,
  FormUI,
  Input,
  Modal,
  Radio,
  SimpleSelect,
  SimpleSelectOption,
  Typography,
} from '@databricks/design-system';
import type { ProjectSummary, UcTable } from '../../../shared/brief';
import { api, PROJECTS_CHANGED, useResource } from '../api';
import { subPath } from '../pages/ProjectsPage';

const q = encodeURIComponent;

/** Import a metric view made outside the app into a new or existing project, as a new sub-project. */
export function ImportModal({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const [catalog, setCatalog] = useState('');
  const [schema, setSchema] = useState('');
  const [view, setView] = useState('');
  const [mode, setMode] = useState<'new' | 'existing'>('new');
  const [parentId, setParentId] = useState('');
  const [projectName, setProjectName] = useState('');
  const [subProject, setSubProject] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  const catalogs = useResource<string[]>('/api/uc/catalogs?purpose=browse');
  const schemas = useResource<string[]>(catalog ? `/api/uc/schemas?catalog=${q(catalog)}` : null);
  const tables = useResource<UcTable[]>(
    catalog && schema ? `/api/uc/tables?catalog=${q(catalog)}&schema=${q(schema)}` : null
  );
  const projects = useResource<ProjectSummary[]>('/api/projects');
  const views = (tables.data ?? []).filter((t) => t.type === 'METRIC_VIEW');
  const sub = subProject ?? view.replace(/_/g, ' ');
  const ready = !!view && !!sub.trim() && (mode === 'new' ? !!projectName.trim() : !!parentId);

  const submit = () => {
    setBusy(true);
    setError(undefined);
    api<{ parentId: string; projectId: string }>('/api/import', {
      view: `${catalog}.${schema}.${view}`,
      parentId: mode === 'existing' ? parentId : null,
      ...(mode === 'new' ? { projectName: projectName.trim() } : {}),
      subProject: sub.trim(),
    }).then(
      (r) => {
        window.dispatchEvent(new Event(PROJECTS_CHANGED));
        onClose();
        void navigate(subPath(r.parentId, r.projectId, 'intake'));
      },
      (err: unknown) => {
        setBusy(false);
        setError((err as Error).message);
      }
    );
  };

  const select = (
    id: string,
    label: string,
    value: string,
    items: (string | { value: string; label: string })[],
    set: (v: string) => void,
    loading: boolean
  ) => (
    <div>
      <FormUI.Label htmlFor={id}>{label}</FormUI.Label>
      <SimpleSelect
        componentId={`gsb.import.${id}`}
        id={id}
        value={value}
        placeholder={loading ? 'Loading' : `Pick a ${label.toLowerCase()}`}
        onChange={(e) => set(e.target.value)}
      >
        {items.map((i) => {
          const o = typeof i === 'string' ? { value: i, label: i } : i;
          return (
            <SimpleSelectOption key={o.value} value={o.value}>
              {o.label}
            </SimpleSelectOption>
          );
        })}
      </SimpleSelect>
    </div>
  );

  return (
    <Modal
      componentId="gsb.import.modal"
      title="Import a metric view"
      visible
      okText="Import"
      cancelText="Cancel"
      okButtonProps={{ disabled: !ready, loading: busy }}
      onCancel={onClose}
      onOk={submit}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Typography.Text color="secondary">
          The app reads the view definition as you and creates a sub-project with its sources, a brief draft to confirm,
          and version 1 of the design. Promote later replaces this view.
        </Typography.Text>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {select(
            'catalog',
            'Catalog',
            catalog,
            catalogs.data ?? [],
            (v) => {
              setCatalog(v);
              setSchema('');
              setView('');
            },
            catalogs.status === 'loading'
          )}
          {catalog &&
            select(
              'schema',
              'Schema',
              schema,
              schemas.data ?? [],
              (v) => {
                setSchema(v);
                setView('');
              },
              schemas.status === 'loading'
            )}
          {schema &&
            select(
              'view',
              'Metric view',
              view,
              views.map((t) => t.name),
              setView,
              tables.status === 'loading'
            )}
        </div>
        {schema && tables.status === 'ready' && !views.length && (
          <Typography.Text color="secondary">No metric views that you can see in this schema.</Typography.Text>
        )}
        <Radio.Group
          componentId="gsb.import.mode"
          name="gsb-import-mode"
          value={mode}
          onChange={(e) => setMode(e.target.value as 'new' | 'existing')}
        >
          <Radio value="new">New project</Radio>
          <Radio value="existing" disabled={!projects.data?.length}>
            Existing project
          </Radio>
        </Radio.Group>
        {mode === 'new' ? (
          <div>
            <FormUI.Label htmlFor="import-project">Project name</FormUI.Label>
            <Input
              componentId="gsb.import.project"
              id="import-project"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
            />
          </div>
        ) : (
          select(
            'parent',
            'Project',
            parentId,
            (projects.data ?? []).map((p) => ({ value: p.id, label: p.name })),
            setParentId,
            projects.status === 'loading'
          )
        )}
        <div>
          <FormUI.Label htmlFor="import-sub">Sub-project name</FormUI.Label>
          <Input
            componentId="gsb.import.sub"
            id="import-sub"
            value={sub}
            onChange={(e) => setSubProject(e.target.value)}
          />
        </div>
        {error && <Alert componentId="gsb.import.error" type="error" closable={false} message={error} />}
      </div>
    </Modal>
  );
}
