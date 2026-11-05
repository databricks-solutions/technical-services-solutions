import { useRef, useState } from 'react';
import {
  Alert,
  Button,
  DownloadIcon,
  Modal,
  Table,
  TableCell,
  TableHeader,
  TableRow,
  Tag,
  Typography,
  UploadIcon,
} from '@databricks/design-system';
import type { DictionaryEntry, DictionaryPreview } from '../../../shared/dictionary';
import { api, useResource } from '../api';
import { downloadExcelTemplate, downloadMarkdownTemplate } from '../dictionaryTemplate';

interface Stored {
  entries: DictionaryEntry[];
  fileName: string | null;
  importedBy: string | null;
  importedAt: string | null;
}

const MAX_KB = 700;
const KIND = { metric: 'Metric', dimension: 'Dimension', term: 'Term' } as const;
const STATUS_COLOR = { draft: 'default', approved: 'indigo', certified: 'teal' } as const;

function Entries({ entries, label }: { entries: DictionaryEntry[]; label: string }) {
  return (
    <Table aria-label={label} scrollable>
      <TableRow isHeader>
        <TableHeader componentId="gsb.dictionary.c_name">Name</TableHeader>
        <TableHeader componentId="gsb.dictionary.c_kind">Kind</TableHeader>
        <TableHeader componentId="gsb.dictionary.c_definition">Definition</TableHeader>
        <TableHeader componentId="gsb.dictionary.c_status">Status</TableHeader>
      </TableRow>
      {entries.map((e) => (
        <TableRow key={`${e.kind}:${e.name}`}>
          <TableCell>
            <div style={{ whiteSpace: 'normal' }}>
              {e.name}
              {e.formula && (
                <div>
                  <code style={{ fontSize: 12 }}>{e.formula}</code>
                </div>
              )}
            </div>
          </TableCell>
          <TableCell>{KIND[e.kind]}</TableCell>
          <TableCell>
            <div style={{ whiteSpace: 'normal' }}>{e.definition}</div>
          </TableCell>
          <TableCell>
            <Tag componentId="gsb.dictionary.status" color={STATUS_COLOR[e.status]}>
              {e.status}
            </Tag>
          </TableCell>
        </TableRow>
      ))}
    </Table>
  );
}

const toBase64 = async (file: File) => {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
};

/** The project's metric dictionary: definitions every sub-project reuses. */
export function DictionaryPanel({ projectId }: { projectId: string }) {
  const stored = useResource<Stored>(`/api/projects/${projectId}/dictionary`);
  const input = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<DictionaryPreview>();
  const [busy, setBusy] = useState<'read' | 'import' | 'clear'>();
  const [clearing, setClearing] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [error, setError] = useState<string>();
  const data = stored.data;
  const count = (k: DictionaryEntry['kind']) => data?.entries.filter((e) => e.kind === k).length ?? 0;

  const read = async (file: File) => {
    setError(undefined);
    if (file.size > MAX_KB * 1024) return setError(`The file is larger than ${MAX_KB} KB.`);
    setBusy('read');
    try {
      setPreview(
        await api<DictionaryPreview>(`/api/projects/${projectId}/dictionary/preview`, {
          fileName: file.name,
          content: await toBase64(file),
        })
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(undefined);
      if (input.current) input.current.value = '';
    }
  };

  const confirm = () => {
    if (!preview) return;
    setBusy('import');
    api(`/api/projects/${projectId}/dictionary/import`, { fileName: preview.fileName, entries: preview.entries }).then(
      () => {
        setBusy(undefined);
        setPreview(undefined);
        stored.refresh();
      },
      (err: unknown) => {
        setBusy(undefined);
        setError((err as Error).message);
      }
    );
  };

  const clear = () => {
    setBusy('clear');
    api(`/api/projects/${projectId}/dictionary/clear`, {}).then(
      () => {
        setBusy(undefined);
        setClearing(false);
        stored.refresh();
      },
      (err: unknown) => {
        setBusy(undefined);
        setClearing(false);
        setError((err as Error).message);
      }
    );
  };

  return (
    <section
      aria-labelledby="gsb-dictionary"
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
        padding: 16,
        border: '1px solid var(--db-border-base)',
        borderRadius: 8,
      }}
    >
      <Typography.Title level={4} withoutMargins id="gsb-dictionary">
        Metric dictionary
      </Typography.Title>
      <Typography.Text color="secondary">
        Your team&apos;s definitions of metrics, dimensions and terms. Every sub-project of this project reuses them:
        the AI, the designer and the table descriptions. Start from the template; it follows the metric view fields, so
        a filled row is ready to certify.
      </Typography.Text>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <Button
          componentId="gsb.dictionary.import"
          type="primary"
          icon={<UploadIcon />}
          loading={busy === 'read'}
          onClick={() => input.current?.click()}
        >
          Import Excel, CSV or Markdown
        </Button>
        <input
          ref={input}
          type="file"
          accept=".xlsx,.csv,.md,.markdown"
          aria-label="Dictionary file"
          style={{ display: 'none' }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void read(f);
          }}
        />
        <Button
          componentId="gsb.dictionary.template_xlsx"
          icon={<DownloadIcon />}
          onClick={() => void downloadExcelTemplate().catch((err: unknown) => setError((err as Error).message))}
        >
          Excel template
        </Button>
        <Button componentId="gsb.dictionary.template_md" icon={<DownloadIcon />} onClick={downloadMarkdownTemplate}>
          Markdown template
        </Button>
        <Typography.Text color="secondary">Up to {MAX_KB} KB and 2,000 rows.</Typography.Text>
      </div>
      {error && <Alert componentId="gsb.dictionary.error" type="error" closable={false} message={error} />}

      {data && data.entries.length > 0 && (
        <>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <Typography.Text>
              {count('metric')} metrics, {count('dimension')} dimensions, {count('term')} terms, from{' '}
              <code>{data.fileName}</code> by {data.importedBy},{' '}
              {data.importedAt ? new Date(data.importedAt).toLocaleString() : ''}.
            </Typography.Text>
            <Button
              componentId="gsb.dictionary.toggle"
              size="small"
              type="tertiary"
              onClick={() => setShowAll(!showAll)}
            >
              {showAll ? 'Hide entries' : 'Show entries'}
            </Button>
            <Button componentId="gsb.dictionary.clear" size="small" danger onClick={() => setClearing(true)}>
              Remove dictionary
            </Button>
          </div>
          {showAll && <Entries entries={data.entries} label="Dictionary entries" />}
        </>
      )}

      {preview && (
        <Modal
          componentId="gsb.dictionary.preview"
          title={`Import ${preview.fileName}`}
          visible
          okText={`Import ${preview.entries.length} entr${preview.entries.length === 1 ? 'y' : 'ies'}`}
          okButtonProps={{ disabled: !preview.entries.length }}
          cancelText="Cancel"
          confirmLoading={busy === 'import'}
          onOk={confirm}
          onCancel={() => setPreview(undefined)}
          size="wide"
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <Typography.Text>
              {preview.added.length} new, {preview.changed.length} changed, {preview.removed.length} removed. The import
              replaces the current dictionary. Nothing is stored until you confirm.
            </Typography.Text>
            {preview.removed.length > 0 && (
              <Alert
                componentId="gsb.dictionary.removed"
                type="warning"
                closable={false}
                message={`Removed: ${preview.removed.join(', ')}`}
              />
            )}
            {preview.problems.length > 0 && (
              <Alert
                componentId="gsb.dictionary.problems"
                type="warning"
                closable={false}
                message={`${preview.problems.length} problem${preview.problems.length === 1 ? '' : 's'} in the file`}
                description={
                  <ul style={{ margin: 0, paddingLeft: 20 }}>
                    {preview.problems.slice(0, 20).map((p) => (
                      <li key={p}>{p}</li>
                    ))}
                  </ul>
                }
              />
            )}
            <Entries entries={preview.entries.slice(0, 200)} label="Entries to import" />
            {preview.entries.length > 200 && (
              <Typography.Text color="secondary">And {preview.entries.length - 200} more.</Typography.Text>
            )}
          </div>
        </Modal>
      )}

      {clearing && (
        <Modal
          componentId="gsb.dictionary.clear_confirm"
          title="Remove the dictionary"
          visible
          okText="Remove"
          okButtonProps={{ danger: true }}
          cancelText="Cancel"
          confirmLoading={busy === 'clear'}
          onOk={clear}
          onCancel={() => setClearing(false)}
        >
          <Typography.Text>
            This removes all {data?.entries.length} entries from the project. Designs and briefs keep what they already
            took from it.
          </Typography.Text>
        </Modal>
      )}
    </section>
  );
}
