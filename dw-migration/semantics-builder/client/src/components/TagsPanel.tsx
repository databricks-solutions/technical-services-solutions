import { useState } from 'react';
import {
  Alert,
  Button,
  FormUI,
  Input,
  Modal,
  SimpleSelect,
  SimpleSelectOption,
  Table,
  TableCell,
  TableHeader,
  TableRow,
  Typography,
} from '@databricks/design-system';
import { SUGGESTED_TAGS } from '../../../shared/govern';
import type { TagsView } from '../../../shared/govern';
import { api, useResource } from '../api';
import { DataState } from './DataState';
import { SqlBlock } from './SqlBlock';

type Tag = { column: string | null; name: string; value: string | null };
const VIEW = '(the view)';

/** Tags on the promoted view and its fields, such as domain or PII. Each change shows its statement first. */
export function TagsPanel({ projectId }: { projectId: string }) {
  const data = useResource<TagsView>(`/api/projects/${projectId}/governance/tags`);
  const [column, setColumn] = useState(VIEW);
  const [name, setName] = useState('');
  const [value, setValue] = useState('');
  const [review, setReview] = useState<Tag & { statement: string }>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const v = data.data;

  const preview = (tag: Tag) => {
    setBusy(true);
    setError(undefined);
    api<{ statement: string }>(`/api/projects/${projectId}/governance/tags/preview`, tag).then(
      (r) => {
        setBusy(false);
        setReview({ ...tag, statement: r.statement });
      },
      (err: unknown) => {
        setBusy(false);
        setError((err as Error).message);
      }
    );
  };
  const run = () => {
    if (!review) return;
    setBusy(true);
    api<TagsView>(`/api/projects/${projectId}/governance/tags`, review).then(
      (next) => {
        setBusy(false);
        setReview(undefined);
        setName('');
        setValue('');
        data.setData(next);
      },
      (err: unknown) => {
        setBusy(false);
        setReview(undefined);
        setError((err as Error).message);
      }
    );
  };

  return (
    <section aria-label="Tags" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Typography.Title level={4} withoutMargins>
        Tags
      </Typography.Title>
      <DataState status={data.status} message={data.error} onRetry={data.reload}>
        {v &&
          (v.problem ? (
            <Typography.Text color="secondary">{v.problem}</Typography.Text>
          ) : (
            <>
              <Typography.Text color="secondary">
                Tags help people find and govern the view in Catalog Explorer, for example its domain, or the fields
                with personal data. A governed tag can have a policy that limits who can set it or its values.
              </Typography.Text>
              {v.tags.length ? (
                <Table aria-label="Tags">
                  <TableRow isHeader>
                    <TableHeader componentId="gsb.tags.h_on">On</TableHeader>
                    <TableHeader componentId="gsb.tags.h_name">Tag</TableHeader>
                    <TableHeader componentId="gsb.tags.h_value">Value</TableHeader>
                    <TableHeader componentId="gsb.tags.h_action"> </TableHeader>
                  </TableRow>
                  {v.tags.map((t) => (
                    <TableRow key={`${t.column ?? ''}:${t.name}`}>
                      <TableCell>{t.column ?? 'The view'}</TableCell>
                      <TableCell>{t.name}</TableCell>
                      <TableCell>{t.value}</TableCell>
                      <TableCell>
                        {v.youOwn && (
                          <Button
                            componentId="gsb.tags.remove"
                            size="small"
                            disabled={busy}
                            onClick={() => preview({ column: t.column, name: t.name, value: null })}
                          >
                            Remove
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </Table>
              ) : (
                <Typography.Text color="secondary">The view and its fields have no tags.</Typography.Text>
              )}
              {v.youOwn ? (
                <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
                  <SimpleSelect
                    componentId="gsb.tags.column"
                    id="tag-column"
                    label="On"
                    value={column}
                    onChange={(e) => setColumn(e.target.value)}
                  >
                    {[VIEW, ...v.columns].map((c) => (
                      <SimpleSelectOption key={c} value={c}>
                        {c}
                      </SimpleSelectOption>
                    ))}
                  </SimpleSelect>
                  <div style={{ minWidth: 200 }}>
                    <FormUI.Label htmlFor="tag-name">Tag</FormUI.Label>
                    <Input
                      componentId="gsb.tags.name"
                      id="tag-name"
                      list="tag-suggestions"
                      placeholder="domain"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                    />
                    <datalist id="tag-suggestions">
                      {SUGGESTED_TAGS.map((s) => (
                        <option key={s} value={s} />
                      ))}
                    </datalist>
                  </div>
                  <div style={{ minWidth: 200 }}>
                    <FormUI.Label htmlFor="tag-value">Value</FormUI.Label>
                    <Input
                      componentId="gsb.tags.value"
                      id="tag-value"
                      placeholder="sales"
                      value={value}
                      onChange={(e) => setValue(e.target.value)}
                    />
                  </div>
                  <Button
                    componentId="gsb.tags.set"
                    disabled={busy || !name.trim() || !value.trim()}
                    onClick={() =>
                      preview({ column: column === VIEW ? null : column, name: name.trim(), value: value.trim() })
                    }
                  >
                    Set the tag
                  </Button>
                </div>
              ) : (
                <Typography.Text color="secondary">Only the owner of the view can change its tags.</Typography.Text>
              )}
            </>
          ))}
      </DataState>
      {error && <Alert componentId="gsb.tags.error" type="error" closable={false} message={error} />}
      {review && (
        <Modal
          componentId="gsb.tags.modal"
          title={review.value === null ? 'Remove a tag' : 'Set a tag'}
          visible
          okText="Run SQL"
          cancelText="Cancel"
          okButtonProps={{ loading: busy }}
          onCancel={() => setReview(undefined)}
          onOk={run}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <Alert
              componentId="gsb.tags.warning"
              type="warning"
              closable={false}
              message="This changes a tag in Unity Catalog, as you. The view and its data do not change."
            />
            <SqlBlock label="SQL" sql={review.statement} />
          </div>
        </Modal>
      )}
    </section>
  );
}
