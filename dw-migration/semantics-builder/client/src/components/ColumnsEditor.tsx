import { useState } from 'react';
import {
  Alert,
  Button,
  CheckIcon,
  CloseIcon,
  Input,
  PencilIcon,
  SparkleIcon,
  Table,
  TableCell,
  TableHeader,
  TableRow,
  Tag,
  Typography,
} from '@databricks/design-system';
import type { ReadinessView, Recommendation } from '../../../shared/readiness';
import { api, useResource } from '../api';
import { MONO } from './SqlBlock';

interface Columns {
  comment: string;
  columns: { name: string; type: string; comment: string }[];
  primaryKey: string[];
  foreignKeys: { columns: string[]; references: string; refColumns: string[] }[];
}

interface Suggestion {
  recId: string;
  index: number;
  text: string;
}

const TABLE = '\u0000table';
const keyOf = (column: string | null) => (column === null ? TABLE : column.toLowerCase());

/** One description: shown, edited in place, or offered by the AI. Save writes it to Unity Catalog as the user. */
function Description({
  label,
  current,
  suggestion,
  busy,
  onSave,
  onPreview,
  onDismiss,
}: {
  label: string;
  current: string;
  suggestion?: Suggestion;
  busy: boolean;
  onSave: (text: string) => Promise<void>;
  onPreview: (text: string) => Promise<string>;
  onDismiss: () => void;
}) {
  const [draft, setDraft] = useState<string>();
  const [sql, setSql] = useState<string>();
  const [error, setError] = useState<string>();
  const save = (text: string) =>
    onSave(text).then(
      () => {
        setDraft(undefined);
        setSql(undefined);
      },
      (err: unknown) => setError((err as Error).message)
    );

  if (draft !== undefined)
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, width: '100%' }}>
        <Input.TextArea
          componentId="gsb.columns.text"
          aria-label={`Description of ${label}`}
          autoSize={{ minRows: 2, maxRows: 8 }}
          maxLength={1000}
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value);
            setSql(undefined);
          }}
        />
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <Button
            componentId="gsb.columns.save"
            type="primary"
            size="small"
            loading={busy}
            disabled={!draft.trim()}
            onClick={() => void save(draft)}
          >
            Save
          </Button>
          <Button componentId="gsb.columns.cancel" size="small" disabled={busy} onClick={() => setDraft(undefined)}>
            Cancel
          </Button>
          <Button
            componentId="gsb.columns.sql"
            size="small"
            type="link"
            disabled={!draft.trim()}
            onClick={() =>
              sql
                ? setSql(undefined)
                : void onPreview(draft).then(setSql, (err: unknown) => setError((err as Error).message))
            }
          >
            {sql ? 'Hide SQL' : 'Show SQL'}
          </Button>
        </div>
        {sql && <code style={{ ...MONO, overflowWrap: 'anywhere' }}>{sql}</code>}
        {error && <Alert componentId="gsb.columns.error" type="error" closable={false} message={error} />}
      </div>
    );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, width: '100%' }}>
      <div style={{ display: 'flex', gap: 4, alignItems: 'flex-start' }}>
        <Typography.Text color={current ? undefined : 'secondary'} style={{ flex: 1 }}>
          {current || 'No description'}
        </Typography.Text>
        <Button
          componentId="gsb.columns.edit"
          size="small"
          type="tertiary"
          icon={<PencilIcon />}
          aria-label={`Edit the description of ${label}`}
          disabled={busy}
          onClick={() => setDraft(current)}
        />
      </div>
      {suggestion && (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 4,
            padding: 8,
            borderRadius: 6,
            background: 'var(--db-surface-subtle)',
          }}
        >
          <Typography.Text size="sm">
            <SparkleIcon /> <b>Suggested:</b> {suggestion.text}
          </Typography.Text>
          <div style={{ display: 'flex', gap: 4 }}>
            <Button
              componentId="gsb.columns.accept"
              size="small"
              icon={<CheckIcon />}
              loading={busy}
              onClick={() => void save(suggestion.text)}
            >
              Accept
            </Button>
            <Button
              componentId="gsb.columns.edit_suggestion"
              size="small"
              disabled={busy}
              onClick={() => setDraft(suggestion.text)}
            >
              Edit
            </Button>
            <Button
              componentId="gsb.columns.dismiss"
              size="small"
              type="tertiary"
              icon={<CloseIcon />}
              disabled={busy}
              onClick={onDismiss}
            >
              Dismiss
            </Button>
          </div>
        </div>
      )}
      {error && <Alert componentId="gsb.columns.error" type="error" closable={false} message={error} />}
    </div>
  );
}

/**
 * A table like the Catalog Explorer columns view: the table description and each column with its type, description
 * and key, edited in place. AI suggestions sit in the cell. Keys open the review, because they also set NOT NULL.
 */
export function ColumnsEditor({
  projectId,
  sourceId,
  fullName,
  view,
  onView,
  onReviewKey,
}: {
  projectId: string;
  sourceId: string;
  fullName: string;
  view: ReadinessView;
  onView: (v: ReadinessView) => void;
  onReviewKey: (r: Recommendation) => void;
}) {
  const live = useResource<Columns>(`/api/projects/${projectId}/sources/${sourceId}/columns`);
  const [busy, setBusy] = useState<string>();
  const [error, setError] = useState<string>();
  const open = view.recommendations.filter(
    (r) => r.sourceName === fullName && (r.status === 'proposed' || r.status === 'failed')
  );
  const suggestions = new Map<string, Suggestion>();
  for (const r of open)
    for (const row of r.rows)
      if (row.kind === 'comment' && !suggestions.has(keyOf(row.column)))
        suggestions.set(keyOf(row.column), { recId: r.id, index: row.index, text: row.proposed });
  const keyFixes = open.filter((r) => r.kind === 'primary_key' || r.kind === 'foreign_key');
  const commentFixes = open.filter((r) => r.kind === 'table_comment' || r.kind === 'column_comments');

  const path = `/api/projects/${projectId}/sources/${sourceId}/comment`;
  const save = (key: string, column: string | null) => (text: string) => {
    setBusy(key);
    return api<{ view: ReadinessView }>(path, { column, text }).then(
      (r) => {
        setBusy(undefined);
        onView(r.view);
        live.reload();
      },
      (err: unknown) => {
        setBusy(undefined);
        throw err;
      }
    );
  };
  const preview = (column: string | null) => (text: string) =>
    api<{ statement: string }>(path, { column, text, preview: true }).then((r) => r.statement);
  const dismiss = (s: Suggestion | undefined) => () => {
    if (!s) return;
    setBusy(`dismiss:${s.recId}`);
    api<ReadinessView>(`/api/projects/${projectId}/recommendations/${s.recId}/dismiss`, { index: s.index }).then(
      (v) => {
        setBusy(undefined);
        onView(v);
      },
      (err: unknown) => {
        setBusy(undefined);
        setError((err as Error).message);
      }
    );
  };
  const acceptAll = async () => {
    setBusy('all');
    setError(undefined);
    try {
      let v = view;
      for (const r of commentFixes)
        v = await api<ReadinessView>(`/api/projects/${projectId}/recommendations/${r.id}/apply`, {
          statements: r.statements,
        });
      onView(v);
      live.reload();
    } catch (err) {
      setError((err as Error).message);
    }
    setBusy(undefined);
  };

  const cols = live.data;
  const keyLabel = (name: string) => {
    if (!cols) return null;
    const tags: string[] = [];
    if (cols.primaryKey.includes(name)) tags.push('PK');
    for (const f of cols.foreignKeys) {
      const i = f.columns.indexOf(name);
      if (i >= 0) tags.push(`FK to ${f.references.split('.').pop()}.${f.refColumns[i]}`);
    }
    return tags;
  };
  const keyFixFor = (name: string) =>
    keyFixes.find((r) => r.rows.some((row) => row.kind === 'key' && row.columns.includes(name)));
  const suggestedCount = suggestions.size;

  if (live.status === 'loading')
    return <Typography.Text color="secondary">Reading the columns as you.</Typography.Text>;
  if (!cols) return <Alert componentId="gsb.columns.load_error" type="error" closable={false} message={live.error} />;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div>
        <Typography.Text bold>Description</Typography.Text>
        <Description
          label={fullName}
          current={cols.comment}
          suggestion={suggestions.get(TABLE)}
          busy={busy === TABLE}
          onSave={save(TABLE, null)}
          onPreview={preview(null)}
          onDismiss={dismiss(suggestions.get(TABLE))}
        />
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Typography.Text bold>Columns ({cols.columns.length})</Typography.Text>
        {suggestedCount > 0 && (
          <Button
            componentId="gsb.columns.accept_all"
            size="small"
            icon={<SparkleIcon />}
            loading={busy === 'all'}
            disabled={!!busy}
            onClick={() => void acceptAll()}
          >
            Accept all {suggestedCount} suggestions
          </Button>
        )}
      </div>
      {error && <Alert componentId="gsb.columns.error_all" type="error" closable={false} message={error} />}
      <Table aria-label={`Columns of ${fullName}`} scrollable>
        <TableRow isHeader>
          <TableHeader componentId="gsb.columns.h_name" style={{ flex: '0 0 22%' }}>
            Name
          </TableHeader>
          <TableHeader componentId="gsb.columns.h_type" style={{ flex: '0 0 12%' }}>
            Type
          </TableHeader>
          <TableHeader componentId="gsb.columns.h_comment" style={{ flex: 4 }}>
            Description
          </TableHeader>
          <TableHeader componentId="gsb.columns.h_key" style={{ flex: '0 0 18%' }}>
            Key
          </TableHeader>
        </TableRow>
        {cols.columns.map((c) => {
          const s = suggestions.get(keyOf(c.name));
          const fix = keyFixFor(c.name);
          return (
            <TableRow key={c.name}>
              <TableCell style={{ flex: '0 0 22%' }}>
                <code style={MONO}>{c.name}</code>
              </TableCell>
              <TableCell style={{ flex: '0 0 12%' }}>{c.type}</TableCell>
              <TableCell multiline style={{ flex: 4 }}>
                <Description
                  label={c.name}
                  current={c.comment}
                  suggestion={c.comment ? undefined : s}
                  busy={busy === keyOf(c.name)}
                  onSave={save(keyOf(c.name), c.name)}
                  onPreview={preview(c.name)}
                  onDismiss={dismiss(s)}
                />
              </TableCell>
              <TableCell multiline style={{ flex: '0 0 18%' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'flex-start' }}>
                  {keyLabel(c.name)?.map((t) => (
                    <Tag key={t} componentId="gsb.columns.key">
                      {t}
                    </Tag>
                  ))}
                  {fix && (
                    <Button componentId="gsb.columns.key_review" size="small" onClick={() => onReviewKey(fix)}>
                      Suggested: {fix.kind === 'primary_key' ? 'PK' : 'FK'}. Review
                    </Button>
                  )}
                </div>
              </TableCell>
            </TableRow>
          );
        })}
      </Table>
    </div>
  );
}
