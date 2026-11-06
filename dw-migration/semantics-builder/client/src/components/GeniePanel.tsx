import { useState } from 'react';
import { Alert, Button, Input, Modal, PlusIcon, Tag, TrashIcon, Typography } from '@databricks/design-system';
import type { GenieCheck, GenieExpected, GenieVerdict, GenieView } from '../../../shared/genie';
import { api, useResource } from '../api';
import { DataState } from './DataState';
import { SqlBlock } from './SqlBlock';
import { FieldPick } from './TestEditor';

type View = GenieView & { setup: string[] };
interface Question {
  question: string;
  expected: GenieExpected;
}

const VERDICT: Record<GenieVerdict, { color: 'teal' | 'coral' | 'lemon' | 'default'; label: string }> = {
  matches: { color: 'teal', label: 'Matches' },
  different: { color: 'coral', label: 'Different fields' },
  no_answer: { color: 'lemon', label: 'No answer' },
  needs_review: { color: 'default', label: 'Needs review' },
  error: { color: 'coral', label: 'Error' },
};

function Check({ c }: { c: GenieCheck }) {
  const [open, setOpen] = useState(false);
  const v = VERDICT[c.verdict];
  return (
    <article
      aria-label={c.question}
      style={{
        border: '1px solid var(--db-border-base)',
        borderRadius: 8,
        padding: 12,
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
      }}
    >
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <Tag componentId="gsb.genie.verdict" color={v.color}>
          {v.label}
        </Tag>
        <Typography.Text bold>{c.question}</Typography.Text>
        <Typography.Text color="secondary" size="sm">
          Version {c.version}, {new Date(c.createdAt).toLocaleString()}
        </Typography.Text>
      </div>
      <Typography.Text>{c.detail}</Typography.Text>
      {(c.answer || c.sql) && (
        <div>
          <Button componentId="gsb.genie.toggle" size="small" type="link" onClick={() => setOpen(!open)}>
            {open ? 'Hide the answer' : 'Show the answer and the SQL'}
          </Button>
        </div>
      )}
      {open && (
        <>
          {c.answer && (
            <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{c.answer}</Typography.Paragraph>
          )}
          {c.sql && <SqlBlock label="SQL that Genie ran" sql={c.sql} />}
        </>
      )}
    </article>
  );
}

/** Ask Genie the business questions on the sandbox view, and check that it uses the expected fields. */
export function GeniePanel({
  projectId,
  fields,
}: {
  projectId: string;
  fields: { measures: string[]; dimensions: string[] };
}) {
  const data = useResource<View>(`/api/projects/${projectId}/genie`);
  const base = useResource<{ workspaceUrl: string | null }>('/api/config').data?.workspaceUrl;
  const [questions, setQuestions] = useState<Question[]>();
  const [reviewing, setReviewing] = useState(false);
  const [busy, setBusy] = useState<string>();
  const [error, setError] = useState<string>();
  const v = data.data;
  const rows =
    questions ?? (v?.keyQuestions ?? []).map((q) => ({ question: q, expected: { measures: [], dimensions: [] } }));
  const put = (i: number, q: Question) => setQuestions(rows.map((x, j) => (j === i ? q : x)));

  const createSpace = () => {
    if (!v) return;
    setBusy('space');
    setError(undefined);
    api<View>(`/api/projects/${projectId}/genie/space`, { statements: v.setup }).then(
      (next) => {
        setBusy(undefined);
        setReviewing(false);
        data.setData(next);
      },
      (err: unknown) => {
        setBusy(undefined);
        setError((err as Error).message);
      }
    );
  };

  const askAll = async () => {
    setError(undefined);
    const todo = rows.filter((q) => q.question.trim().length >= 3);
    for (const [i, q] of todo.entries()) {
      setBusy(`Asking ${i + 1} of ${todo.length}: ${q.question}`);
      try {
        const expected = q.expected.measures.length || q.expected.dimensions.length ? q.expected : null;
        data.setData(
          await api<View>(`/api/projects/${projectId}/genie/ask`, { question: q.question.trim(), expected })
        );
      } catch (err) {
        setError((err as Error).message);
        break;
      }
    }
    setBusy(undefined);
  };

  return (
    <DataState status={data.status} message={data.error} onRetry={data.reload}>
      {v && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Typography.Text color="secondary">
            Genie answers the business questions on the sandbox view of the validated version, as you. For each
            question, pick the measures and dimensions a correct answer uses; the app checks Genie&apos;s SQL against
            them. Questions run SQL on the SQL warehouse.
          </Typography.Text>
          {v.version === null ? (
            <Alert
              componentId="gsb.genie.not_validated"
              type="info"
              closable={false}
              message="Validate the design before you ask Genie."
            />
          ) : !v.space ? (
            <div>
              <Button componentId="gsb.genie.create" type="primary" onClick={() => setReviewing(true)}>
                Create the Genie space
              </Button>
            </div>
          ) : (
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <Typography.Text>
                Genie space on <code>{v.space.view}</code>
              </Typography.Text>
              {base && (
                <Typography.Link
                  componentId="gsb.genie.open"
                  href={`${base}/genie/rooms/${encodeURIComponent(v.space.spaceId)}`}
                  openInNewTab
                >
                  Open in Genie
                </Typography.Link>
              )}
              <Button
                componentId="gsb.genie.refresh_view"
                size="small"
                disabled={!!busy}
                onClick={() => setReviewing(true)}
              >
                Update the sandbox view
              </Button>
            </div>
          )}

          {v.space && (
            <section aria-label="Questions" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <Typography.Title level={4} withoutMargins>
                Questions
              </Typography.Title>
              {rows.map((q, i) => (
                <fieldset
                  // Rows have no stable id; the inputs are controlled, so an index key cannot leave stale text.
                  // eslint-disable-next-line react/no-array-index-key
                  key={i}
                  style={{
                    border: '1px solid var(--db-border-base)',
                    borderRadius: 8,
                    padding: 12,
                    margin: 0,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 8,
                  }}
                >
                  <div style={{ display: 'flex', gap: 8 }}>
                    <Input
                      componentId="gsb.genie.question"
                      aria-label={`Question ${i + 1}`}
                      value={q.question}
                      onChange={(e) => put(i, { ...q, question: e.target.value })}
                    />
                    <Button
                      componentId="gsb.genie.remove"
                      icon={<TrashIcon />}
                      aria-label={`Remove question ${i + 1}`}
                      onClick={() => setQuestions(rows.filter((_, j) => j !== i))}
                    />
                  </div>
                  <FieldPick
                    label="Expected measures"
                    names={fields.measures}
                    value={q.expected.measures}
                    onChange={(m) => put(i, { ...q, expected: { ...q.expected, measures: m } })}
                  />
                  <FieldPick
                    label="Expected dimensions"
                    names={fields.dimensions}
                    value={q.expected.dimensions}
                    onChange={(d) => put(i, { ...q, expected: { ...q.expected, dimensions: d } })}
                  />
                </fieldset>
              ))}
              <div style={{ display: 'flex', gap: 8 }}>
                <Button
                  componentId="gsb.genie.add"
                  size="small"
                  icon={<PlusIcon />}
                  onClick={() => setQuestions([...rows, { question: '', expected: { measures: [], dimensions: [] } }])}
                >
                  Add a question
                </Button>
                <Button
                  componentId="gsb.genie.ask"
                  type="primary"
                  loading={!!busy && busy !== 'space'}
                  disabled={!!busy || !rows.some((q) => q.question.trim().length >= 3)}
                  onClick={() => void askAll()}
                >
                  Ask Genie
                </Button>
              </div>
              {busy && busy !== 'space' && (
                <div role="status">
                  <Typography.Text color="secondary">{busy}. Each question can take a minute.</Typography.Text>
                </div>
              )}
            </section>
          )}

          {error && <Alert componentId="gsb.genie.error" type="error" closable={false} message={error} />}

          {v.checks.length > 0 && (
            <section aria-label="Answers" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <Typography.Title level={4} withoutMargins>
                Answers ({v.checks.length})
              </Typography.Title>
              {v.checks.map((c) => (
                <Check key={c.id} c={c} />
              ))}
            </section>
          )}

          <Modal
            componentId="gsb.genie.space_modal"
            title={v.space ? 'Update the sandbox view' : 'Create the Genie space'}
            visible={reviewing}
            okText="Run SQL"
            cancelText="Cancel"
            okButtonProps={{ loading: busy === 'space' }}
            onCancel={() => setReviewing(false)}
            onOk={createSpace}
          >
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <Alert
                componentId="gsb.genie.space_warning"
                type="warning"
                closable={false}
                message="This replaces the sandbox view with the validated version, as you. Then the app creates one Genie space on it, as you, if none exists for this view."
              />
              {v.setup.map((s) => (
                <SqlBlock key={s} label="SQL" sql={s} />
              ))}
            </div>
          </Modal>
        </div>
      )}
    </DataState>
  );
}
