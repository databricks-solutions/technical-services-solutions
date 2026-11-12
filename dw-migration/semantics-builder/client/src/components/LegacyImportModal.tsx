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
  const [file, setFile] = useState<{ name: string; content: string; base64: boolean }>();
  const [schema, setSchema] = useState('');
  const [subProject, setSubProject] = useState('');
  const [preview, setPreview] = useState<LegacyPreview>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const body = (create: boolean) => ({
    fileName: file?.name,
    content: file?.content,
    encoding: file?.base64 ? 'base64' : 'text',
    // The AI SQL of the preview goes back unchanged, so the sub-project gets what you saw.
    ...(create && preview?.ai ? { ai: preview.ai } : {}),
    ...(schema.trim() ? { schema: schema.trim() } : {}),
    subProject: subProject.trim() || 'Imported model',
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
          dbt MetricFlow: a YAML file with semantic_models and metrics, or the semantic_manifest.json of dbt parse.
          LookML: the .view.lkml files and the model file with the explore. Power BI: a .pbit template. SSAS Tabular: a
          .bim file. Tableau: a workbook or a data source. Cognos: the model.xml of a Framework Manager project.
          MicroStrategy: one JSON file with the tables, attributes, facts and metrics of the REST Modeling API. SSAS
          Multidimensional: the .dsv, .dim and .cube files of the project, or an .xmla script. The app converts the
          model by rules into a draft metric view in a new sub-project. For an expression that has no rule, the AI
          suggests SQL, which you check. Each field keeps its source definition and a status. The files are only read;
          the app does not run them.
        </Typography.Text>
        <div>
          <FormUI.Label htmlFor="legacy-file">
            Files (dbt: .yml, .yaml or .json; LookML: one or more .lkml; Power BI: .pbit; Tabular: .bim; Tableau: .twb,
            .tds, .twbx or .tdsx; Cognos: model.xml; MicroStrategy: .json; SSAS: .dsv, .dim and .cube, or .xmla)
          </FormUI.Label>
          <input
            id="legacy-file"
            type="file"
            accept=".yml,.yaml,.json,.lkml,.bim,.pbit,.twb,.tds,.twbx,.tdsx,.xml,.dsv,.dim,.cube,.xmla"
            multiple
            onChange={(e) => {
              const files = [...(e.target.files ?? [])];
              setPreview(undefined);
              setError(undefined);
              if (!files.length) return setFile(undefined);
              if (files.reduce((n, f) => n + f.size, 0) > MAX_LEGACY_BYTES)
                return setError('The files are larger than 10 MB together.');
              // A .pbit template and a packaged Tableau file are zips: they go as base64.
              if (/\.(pbit|twbx|tdsx)$/i.test(files[0].name)) {
                // base64 is 4/3 of the size, and the server takes 10 MB.
                if ((files[0].size * 4) / 3 > MAX_LEGACY_BYTES)
                  return setError(
                    'The file is larger than 7.5 MB. For Tableau, save the workbook as .twb without extracts.'
                  );
                void files[0].arrayBuffer().then((buf) => {
                  let bin = '';
                  new Uint8Array(buf).forEach((b) => (bin += String.fromCharCode(b)));
                  setFile({ name: files[0].name, content: btoa(bin), base64: true });
                });
                return;
              }
              // LookML views and the model with the explore are often in separate files, and so are the .dsv, .dim
              // and .cube files of an SSAS project: they are read as one.
              const ext = files.every((f) => /\.(dsv|dim|cube)$/i.test(f.name)) ? 'ssas' : 'lkml';
              void Promise.all(files.map((f) => f.text())).then((texts) =>
                setFile({
                  name: files.length === 1 ? files[0].name : `${files.length} files.${ext}`,
                  content: texts.join('\n'),
                  base64: false,
                })
              );
            }}
          />
        </div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <div style={{ minWidth: 260 }}>
            <FormUI.Label htmlFor="legacy-schema">Default catalog.schema of the tables</FormUI.Label>
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
              placeholder="Imported model"
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
                <TableHeader componentId="gsb.legacy.h_source">Source definition</TableHeader>
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
