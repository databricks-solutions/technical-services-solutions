import { useState } from 'react';
import { useNavigate } from 'react-router';
import {
  Alert,
  FormUI,
  Input,
  Modal,
  Table,
  TableCell,
  TableHeader,
  TableRow,
  Tag,
  Typography,
} from '@databricks/design-system';
import { MAX_LEGACY_BYTES } from '../../../shared/legacy';
import type { FieldStatus, LegacyPreview } from '../../../shared/legacy';
import { api, PROJECTS_CHANGED } from '../api';
import { subPath } from '../pages/ProjectsPage';
import { SqlBlock } from './SqlBlock';

const STATUS: Record<FieldStatus, { color: 'teal' | 'lemon' | 'coral'; label: string }> = {
  converted: { color: 'teal', label: 'Converted' },
  review: { color: 'lemon', label: 'Check it' },
  manual: { color: 'coral', label: 'Not converted' },
};

/**
 * Import a legacy semantic model as a new sub-project with a draft metric view. dbt MetricFlow first: a
 * semantic_models YAML file or semantic_manifest.json. The preview shows each field, its source and its status.
 */
export function LegacyImportModal({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const navigate = useNavigate();
  const [file, setFile] = useState<{ name: string; content: string }>();
  const [schema, setSchema] = useState('');
  const [subProject, setSubProject] = useState('');
  const [preview, setPreview] = useState<LegacyPreview>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const body = (create: boolean) => ({
    fileName: file?.name,
    content: file?.content,
    ...(schema.trim() ? { schema: schema.trim() } : {}),
    subProject: subProject.trim() || 'Imported from dbt',
    create,
  });

  const run = (create: boolean) => {
    setBusy(true);
    setError(undefined);
    api<LegacyPreview | { parentId: string; projectId: string }>(
      `/api/projects/${projectId}/import/legacy`,
      body(create)
    ).then(
      (r) => {
        setBusy(false);
        if ('projectId' in r) {
          window.dispatchEvent(new Event(PROJECTS_CHANGED));
          void navigate(subPath(r.parentId, r.projectId, 'designer'));
        } else setPreview(r);
      },
      (err: unknown) => {
        setBusy(false);
        setError((err as Error).message);
      }
    );
  };

  return (
    <Modal
      componentId="gsb.legacy.modal"
      title="Import a legacy semantic model"
      visible
      size="wide"
      okText={preview ? 'Create the sub-project' : 'Preview'}
      cancelText="Cancel"
      okButtonProps={{ loading: busy, disabled: !file || (!!preview && !preview.yaml) }}
      onCancel={onClose}
      onOk={() => run(!!preview)}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Typography.Text color="secondary">
          dbt MetricFlow: a YAML file with semantic_models and metrics, or the semantic_manifest.json of dbt parse. The
          app converts it by rules into a draft metric view in a new sub-project. Each field keeps its dbt definition
          and a status. The file is only read; the app does not run it.
        </Typography.Text>
        <div>
          <FormUI.Label htmlFor="legacy-file">File (.yml, .yaml or .json)</FormUI.Label>
          <input
            id="legacy-file"
            type="file"
            accept=".yml,.yaml,.json"
            onChange={(e) => {
              const f = e.target.files?.[0];
              setPreview(undefined);
              setError(undefined);
              if (!f) return setFile(undefined);
              if (f.size > MAX_LEGACY_BYTES) return setError('The file is larger than 800 KB.');
              void f.text().then((content) => setFile({ name: f.name, content }));
            }}
          />
        </div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <div style={{ minWidth: 260 }}>
            <FormUI.Label htmlFor="legacy-schema">Catalog.schema of the dbt models (for ref())</FormUI.Label>
            <Input
              componentId="gsb.legacy.schema"
              id="legacy-schema"
              placeholder="main.analytics"
              value={schema}
              onChange={(e) => {
                setSchema(e.target.value);
                setPreview(undefined);
              }}
            />
          </div>
          <div style={{ minWidth: 260 }}>
            <FormUI.Label htmlFor="legacy-sub">Sub-project name</FormUI.Label>
            <Input
              componentId="gsb.legacy.sub"
              id="legacy-sub"
              placeholder="Imported from dbt"
              maxLength={200}
              value={subProject}
              onChange={(e) => setSubProject(e.target.value)}
            />
          </div>
        </div>
        {error && <Alert componentId="gsb.legacy.error" type="error" closable={false} message={error} />}
        {preview && (
          <>
            {preview.issues.map((i) => (
              <Alert key={i} componentId="gsb.legacy.issue" type="warning" closable={false} message={i} />
            ))}
            <Typography.Text>
              Tables: {preview.sources.join(', ') || 'none'}.{' '}
              {preview.fields.filter((f) => f.status === 'converted').length} converted,{' '}
              {preview.fields.filter((f) => f.status === 'review').length} to check,{' '}
              {preview.fields.filter((f) => f.status === 'manual').length} not converted. Fields that are not converted
              go to the open questions of the brief.
            </Typography.Text>
            <Table aria-label="Converted fields">
              <TableRow isHeader>
                <TableHeader componentId="gsb.legacy.h_name">Field</TableHeader>
                <TableHeader componentId="gsb.legacy.h_status">Status</TableHeader>
                <TableHeader componentId="gsb.legacy.h_source">dbt definition</TableHeader>
                <TableHeader componentId="gsb.legacy.h_note">Note</TableHeader>
              </TableRow>
              {preview.fields.map((f) => (
                <TableRow key={`${f.kind}:${f.name}`}>
                  <TableCell>
                    {f.name} ({f.kind})
                  </TableCell>
                  <TableCell>
                    <Tag componentId="gsb.legacy.status" color={STATUS[f.status].color}>
                      {STATUS[f.status].label}
                    </Tag>
                  </TableCell>
                  <TableCell>{f.source}</TableCell>
                  <TableCell>{f.note}</TableCell>
                </TableRow>
              ))}
            </Table>
            {preview.yaml && <SqlBlock label="Draft metric view (YAML)" sql={preview.yaml} />}
          </>
        )}
      </div>
    </Modal>
  );
}
