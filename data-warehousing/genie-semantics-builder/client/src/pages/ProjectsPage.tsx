import { useState } from 'react';
import { useNavigate } from 'react-router';
import {
  Button,
  FormUI,
  Input,
  Modal,
  PlusIcon,
  Table,
  TableCell,
  TableHeader,
  TableRow,
  Typography,
} from '@databricks/design-system';
import type { NewProject, Project } from '../../../shared/brief';
import { api, useResource } from '../api';
import { DataState } from '../components/DataState';
import { CatalogSchemaSelect } from '../components/UcPicker';

function NewProjectModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const [form, setForm] = useState<NewProject>({ name: '' });
  const [error, setError] = useState<string>();
  const [saving, setSaving] = useState(false);
  const field = (key: keyof NewProject) => ({
    value: form[key] ?? '',
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setForm((prev) => ({ ...prev, [key]: e.target.value || undefined })),
  });

  const submit = () => {
    setSaving(true);
    setError(undefined);
    api<Project>('/api/projects', form).then(
      (p) => void navigate(`/projects/${p.id}/intake`),
      (err: unknown) => {
        setError((err as Error).message);
        setSaving(false);
      }
    );
  };

  return (
    <Modal
      componentId="gsb.projects.new_modal"
      title="New project"
      visible={open}
      okText="Create project"
      onOk={submit}
      okButtonProps={{ loading: saving, disabled: !form.name.trim() }}
      cancelText="Cancel"
      onCancel={onClose}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div>
          <FormUI.Label htmlFor="gsb-project-name" required>
            Name
          </FormUI.Label>
          <Input componentId="gsb.projects.name" id="gsb-project-name" {...field('name')} maxLength={200} />
        </div>
        <div>
          <FormUI.Label htmlFor="gsb-project-description">Description</FormUI.Label>
          <Input.TextArea
            componentId="gsb.projects.description"
            id="gsb-project-description"
            {...field('description')}
            maxLength={4000}
          />
        </div>
        <div role="group" aria-labelledby="gsb-project-target-label">
          <FormUI.Label id="gsb-project-target-label">Target location</FormUI.Label>
          <FormUI.Hint>Where metric views will be published.</FormUI.Hint>
          <CatalogSchemaSelect
            idPrefix="target"
            catalog={form.targetCatalog}
            schema={form.targetSchema}
            onChange={(targetCatalog, targetSchema) => setForm((prev) => ({ ...prev, targetCatalog, targetSchema }))}
          />
        </div>
        {error && <FormUI.Message type="error" message={error} />}
      </div>
    </Modal>
  );
}

export function ProjectsPage() {
  const navigate = useNavigate();
  const projects = useResource<Project[]>('/api/projects');
  const [creating, setCreating] = useState(false);
  const newButton = (
    <Button componentId="gsb.projects.new" type="primary" icon={<PlusIcon />} onClick={() => setCreating(true)}>
      New project
    </Button>
  );

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>{projects.data?.length ? newButton : null}</div>
      <DataState
        status={projects.status === 'ready' && !projects.data?.length ? 'empty' : projects.status}
        message={projects.error ?? 'Create a project to start a semantic model.'}
        emptyAction={newButton}
        onRetry={projects.reload}
      >
        <Table>
          <TableRow isHeader>
            <TableHeader componentId="gsb.projects.col_name">Name</TableHeader>
            <TableHeader componentId="gsb.projects.col_target">Target</TableHeader>
            <TableHeader componentId="gsb.projects.col_created">Created</TableHeader>
          </TableRow>
          {projects.data?.map((p) => (
            <TableRow key={p.id}>
              <TableCell>
                <Typography.Link
                  componentId="gsb.projects.open"
                  href={`/projects/${p.id}/intake`}
                  onClick={(e) => {
                    e.preventDefault();
                    void navigate(`/projects/${p.id}/intake`);
                  }}
                >
                  {p.name}
                </Typography.Link>
              </TableCell>
              <TableCell>{p.targetCatalog ? `${p.targetCatalog}.${p.targetSchema ?? '*'}` : 'Not set'}</TableCell>
              <TableCell>{new Date(p.createdAt).toLocaleDateString()}</TableCell>
            </TableRow>
          ))}
        </Table>
      </DataState>
      {creating && <NewProjectModal open={creating} onClose={() => setCreating(false)} />}
    </>
  );
}
