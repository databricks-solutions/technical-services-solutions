import { useState } from 'react';
import type { ReactNode } from 'react';
import { useNavigate } from 'react-router';
import {
  Alert,
  Input,
  Modal,
  Table,
  TableCell,
  TableHeader,
  TableRow,
  Tag,
  Typography,
} from '@databricks/design-system';
import { fitsTool, LEGACY_TOOLS, legacyTool, MAX_LEGACY_BYTES } from '../../../shared/legacy';
import type { FieldStatus, LegacyPreview, LegacyTool } from '../../../shared/legacy';
import { api, PROJECTS_CHANGED } from '../api';
import { subPath } from '../pages/ProjectsPage';
import { SqlBlock } from './SqlBlock';
import { SchemaPicker } from './UcPicker';

const STATUS: Record<FieldStatus, { color: 'teal' | 'lemon' | 'coral'; label: string }> = {
  converted: { color: 'teal', label: 'Converted' },
  review: { color: 'lemon', label: 'Check it' },
  manual: { color: 'coral', label: 'Not converted' },
};

const HELP: Record<LegacyTool, string> = {
  dbt: 'A YAML file with semantic_models and metrics, or the semantic_manifest.json of dbt parse.',
  lookml: 'The .view.lkml files and the model file with the explore. Choose them together.',
  powerbi: 'A .pbit template, or all the .tmdl files of the definition folder of a Power BI project, chosen together.',
  tabular: 'The .bim file of the model.',
  tableau: 'A workbook or a data source. A packaged file (.twbx, .tdsx) can be up to 7.5 MB; save it without extracts.',
  cognos: 'The model.xml of a Framework Manager project.',
  microstrategy: 'One JSON file with the tables, attributes, facts and metrics of the REST Modeling API.',
  ssas: 'The .dsv, .dim and .cube files of the project, chosen together, or one .xmla script.',
};
const SCHEMA_HELP: Record<LegacyTool, string> = {
  dbt: 'For ref() in YAML files. Leave it empty for a manifest, which names its tables.',
  lookml: 'For sql_table_name values with no catalog. Leave it empty when every view names its catalog.',
  powerbi:
    'For tables with no Databricks connector in their Power Query source. Leave it empty when all tables use it.',
  tabular: 'For tables with no Databricks connector in their source. Leave it empty when all tables use it.',
  tableau: 'For tables with no catalog in the connection. Leave it empty when the connection names it.',
  cognos: 'Pick the schema of the tables. The model names them in its SQL only.',
  microstrategy: 'Pick the schema of the tables. The project names them by their warehouse names only.',
  ssas: 'Pick the schema of the tables. The data source view names them by their warehouse names only.',
};

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <section aria-label={title} style={{ display: 'flex', gap: 12 }}>
      <span
        aria-hidden
        style={{
          flex: '0 0 24px',
          height: 24,
          borderRadius: 12,
          display: 'grid',
          placeItems: 'center',
          fontSize: 12,
          fontWeight: 600,
          background: 'var(--db-accent-surface-subtle)',
          color: 'var(--db-accent-text)',
        }}
      >
        {n}
      </span>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, flex: 1, minWidth: 0 }}>
        <Typography.Text bold>{title}</Typography.Text>
        {children}
      </div>
    </section>
  );
}

/**
 * Import a legacy semantic model as a new sub-project with a draft metric view. Pick the tool, its files, the default
 * catalog and schema, and a name. The preview shows each field, its source and its status.
 */
export function LegacyImportModal({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const navigate = useNavigate();
  const [tool, setTool] = useState<LegacyTool>();
  const [file, setFile] = useState<{ name: string; content: string; base64: boolean; count: number }>();
  const [schema, setSchema] = useState('');
  const [subProject, setSubProject] = useState('');
  const [preview, setPreview] = useState<LegacyPreview>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const body = (create: boolean) => ({
    fileName: file?.name,
    content: file?.content,
    encoding: file?.base64 ? 'base64' : 'text',
    tool,
    // The AI SQL of the preview goes back unchanged, so the sub-project gets what you saw.
    ...(create && preview?.ai ? { ai: preview.ai } : {}),
    ...(schema.trim() ? { schema: schema.trim() } : {}),
    subProject: subProject.trim() || 'Imported model',
    create,
  });

  const pickTool = (t: LegacyTool) => {
    if (t === tool) return;
    setTool(t);
    setFile(undefined);
    setPreview(undefined);
    setError(undefined);
  };

  /** The chosen files as one model, after a check of their extensions and sizes. */
  const readFiles = (files: File[]) => {
    setPreview(undefined);
    setError(undefined);
    setFile(undefined);
    if (!tool || !files.length) return;
    const t = legacyTool(tool);
    const wrong = files.filter((f) => !fitsTool(tool, f.name));
    if (wrong.length)
      return setError(`${t.label} reads ${t.exts.join(', ')} files. Not: ${wrong.map((f) => f.name).join(', ')}.`);
    if (files.length > 1 && files.some((f) => /\.(pbit|xmla)$/i.test(f.name)))
      return setError('Choose one .pbit or .xmla file alone, or the text files of the project together.');
    if (files.reduce((n, f) => n + f.size, 0) > MAX_LEGACY_BYTES)
      return setError('The files are larger than 10 MB together.');
    // A .pbit template and a packaged Tableau file are zips: they go as base64, which is 4/3 of the size.
    if (/\.(pbit|twbx|tdsx)$/i.test(files[0].name)) {
      if ((files[0].size * 4) / 3 > MAX_LEGACY_BYTES)
        return setError('The file is larger than 7.5 MB. For Tableau, save the workbook as .twb without extracts.');
      void files[0].arrayBuffer().then((buf) => {
        let bin = '';
        new Uint8Array(buf).forEach((b) => (bin += String.fromCharCode(b)));
        setFile({ name: files[0].name, content: btoa(bin), base64: true, count: 1 });
      });
      return;
    }
    // Several files of one tool (LookML views, TMDL tables, SSAS .dsv, .dim and .cube) are read as one model.
    const joined = { lookml: 'lkml', powerbi: 'tmdl', ssas: 'ssas' } as Partial<Record<LegacyTool, string>>;
    void Promise.all(files.map((f) => f.text())).then((texts) =>
      setFile({
        name: files.length === 1 ? files[0].name : `${files.length} files.${joined[tool] ?? 'txt'}`,
        content: texts.join('\n'),
        base64: false,
        count: files.length,
      })
    );
  };

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
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <Typography.Text color="secondary">
          The app converts a semantic model of another tool into a draft metric view in a new sub-project. Rules convert
          it first; for an expression with no rule, the AI suggests SQL that you check. Each field keeps its source
          definition and a status. The files are only read, never run.
        </Typography.Text>

        <Step n={1} title="Technology">
          <div
            role="radiogroup"
            aria-label="Technology"
            style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))', gap: 8 }}
          >
            {LEGACY_TOOLS.map((t) => {
              const on = t.id === tool;
              return (
                <button
                  key={t.id}
                  type="button"
                  role="radio"
                  aria-checked={on}
                  onClick={() => pickTool(t.id)}
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 2,
                    padding: '8px 12px',
                    borderRadius: 8,
                    border: `${on ? 2 : 1}px solid ${on ? 'var(--db-accent-text)' : 'var(--db-border-base)'}`,
                    background: on ? 'var(--db-accent-surface-subtle)' : 'var(--db-surface-base)',
                    color: 'var(--db-text-base)',
                    cursor: 'pointer',
                    textAlign: 'left',
                    font: 'inherit',
                  }}
                >
                  <span style={{ fontWeight: 600 }}>{t.label}</span>
                  <span style={{ fontSize: 12, color: 'var(--db-text-subtle)' }}>{t.exts.join(' ')}</span>
                </button>
              );
            })}
          </div>
          {tool && <Typography.Text color="secondary">{HELP[tool]}</Typography.Text>}
        </Step>

        {tool && (
          <Step n={2} title={legacyTool(tool).multiple ? 'Files' : 'File'}>
            <input
              key={tool}
              id="legacy-file"
              aria-label={`${legacyTool(tool).label} files`}
              type="file"
              accept={legacyTool(tool).exts.join(',')}
              multiple={legacyTool(tool).multiple}
              onChange={(e) => readFiles([...(e.target.files ?? [])])}
            />
            {file && file.count > 1 && (
              <Typography.Text color="secondary">{file.count} files, read as one model.</Typography.Text>
            )}
          </Step>
        )}

        {tool && (
          <Step n={3} title="Default catalog and schema">
            <Typography.Text color="secondary">{SCHEMA_HELP[tool]}</Typography.Text>
            <SchemaPicker
              value={schema}
              onChange={(v) => {
                setSchema(v);
                setPreview(undefined);
              }}
            />
          </Step>
        )}

        {tool && (
          <Step n={4} title="Sub-project name">
            <div style={{ maxWidth: 420 }}>
              <Input
                componentId="gsb.legacy.sub"
                id="legacy-sub"
                aria-label="Sub-project name"
                placeholder="Imported model"
                maxLength={200}
                value={subProject}
                onChange={(e) => setSubProject(e.target.value)}
              />
            </div>
          </Step>
        )}

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
