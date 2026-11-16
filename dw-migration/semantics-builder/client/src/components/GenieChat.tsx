import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router';
import {
  Alert,
  Button,
  CloseIcon,
  Input,
  SendIcon,
  SimpleSelect,
  SimpleSelectOption,
  Table,
  TableCell,
  TableHeader,
  TableRow,
  Typography,
} from '@databricks/design-system';
import { testFromAnswer } from '../../../shared/genie';
import type { ChatAnswer, GenieEngine, GenieView } from '../../../shared/genie';
import { api, useResource } from '../api';
import { subPath } from '../pages/ProjectsPage';
import { SqlBlock } from './SqlBlock';

interface Turn {
  question: string;
  engine: GenieEngine;
  answer?: ChatAnswer;
  error?: string;
}

const ENGINE: Record<GenieEngine, string> = { space: 'Genie Agent', one: 'Genie One' };

function Answer({ turn, onTest, onAsk }: { turn: Turn; onTest: () => void; onAsk: (q: string) => void }) {
  const a = turn.answer;
  if (turn.error) return <Alert componentId="gsb.chat.error" type="error" closable={false} message={turn.error} />;
  if (!a) return null;
  const used = [...a.fields.measures, ...a.fields.dimensions];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {a.text && <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{a.text}</Typography.Paragraph>}
      {!a.text && !a.sql && <Typography.Text color="secondary">Genie gave no answer.</Typography.Text>}
      {a.sql && (
        <Typography.Text color="secondary" size="sm">
          Fields of the view: {used.join(', ') || 'none'}.
        </Typography.Text>
      )}
      {a.read && (
        <Typography.Text color="secondary" size="sm">
          Read: {a.read.assets.join(', ') || 'no object listed'}.
          {a.read.snippets && ' It also searched workspace knowledge snippets, which other users may have written.'}
        </Typography.Text>
      )}
      {a.table && (
        <div style={{ overflowX: 'auto' }}>
          <Table aria-label={`Result of: ${turn.question}`}>
            <TableRow isHeader>
              {a.table.columns.map((c, i) => (
                // Column names can repeat in a result.
                // eslint-disable-next-line react/no-array-index-key
                <TableHeader key={i} componentId="gsb.chat.col">
                  {c}
                </TableHeader>
              ))}
            </TableRow>
            {a.table.rows.map((r, i) => (
              // A result row has no id.
              // eslint-disable-next-line react/no-array-index-key
              <TableRow key={i}>
                {r.map((v, j) => (
                  // eslint-disable-next-line react/no-array-index-key
                  <TableCell key={j}>{v ?? 'null'}</TableCell>
                ))}
              </TableRow>
            ))}
          </Table>
          {a.table.truncated && (
            <Typography.Text color="secondary" size="sm">
              The first rows and columns only.
            </Typography.Text>
          )}
        </div>
      )}
      {a.sql && <SqlBlock label="SQL that Genie ran" sql={a.sql} />}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {testFromAnswer(turn.question, a) && (
          <Button componentId="gsb.chat.test" size="small" onClick={onTest}>
            Use as a test
          </Button>
        )}
        {a.suggested.map((q) => (
          <Button key={q} componentId="gsb.chat.suggested" size="small" type="link" onClick={() => onAsk(q)}>
            {q}
          </Button>
        ))}
      </div>
    </div>
  );
}

/** The Genie side panel of one sub-project. It asks about the sandbox view of the validated version, as you. */
export function GenieChat({
  parentId,
  projectId,
  onClose,
}: {
  parentId: string;
  projectId: string;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const { pathname, search } = useLocation();
  const genie = useResource<GenieView>(`/api/projects/${projectId}/genie`);
  const info = genie.data;
  const { refresh } = genie;
  // Pages validate the design and create the space, so the scope refreshes on each navigation.
  useEffect(() => refresh(), [pathname, search, refresh]);
  const [engine, setEngine] = useState<GenieEngine>('space');
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);
  // Follow-ups go to the last Genie Agent conversation. The id is kept here only, never stored.
  const conversationId = [...turns].reverse().find((t) => t.engine === 'space' && t.answer?.conversationId)
    ?.answer?.conversationId;
  const ready = info?.version !== null && info?.version !== undefined && (engine === 'one' || !!info.space);

  const ask = (q: string) => {
    const text = q.trim();
    if (text.length < 3 || busy) return;
    const turn: Turn = { question: text, engine };
    setTurns((t) => [...t, turn]);
    setQuestion('');
    setBusy(true);
    const body = { question: text, engine, ...(engine === 'space' && conversationId ? { conversationId } : {}) };
    api<ChatAnswer>(`/api/projects/${projectId}/genie/chat`, body).then(
      (answer) => {
        setBusy(false);
        setTurns((t) => t.map((x) => (x === turn ? { ...x, answer } : x)));
      },
      (err: unknown) => {
        setBusy(false);
        setTurns((t) => t.map((x) => (x === turn ? { ...x, error: (err as Error).message } : x)));
      }
    );
  };

  const openAsTest = (turn: Turn) => {
    const test = turn.answer && testFromAnswer(turn.question, turn.answer);
    if (test) void navigate(subPath(parentId, projectId, 'designer?tab=tests'), { state: { test } });
  };

  return (
    <aside
      aria-label="Genie"
      style={{
        width: 420,
        flexShrink: 0,
        borderLeft: '1px solid var(--db-border-base)',
        display: 'flex',
        flexDirection: 'column',
        minHeight: 0,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '12px 16px' }}>
        <Typography.Title level={4} withoutMargins>
          Genie
        </Typography.Title>
        <div style={{ flex: 1 }} />
        <Button componentId="gsb.chat.new" size="small" disabled={busy || !turns.length} onClick={() => setTurns([])}>
          New chat
        </Button>
        <Button
          componentId="gsb.chat.close"
          size="small"
          icon={<CloseIcon />}
          aria-label="Close Genie"
          onClick={onClose}
        />
      </div>
      <div style={{ padding: '0 16px 8px', display: 'flex', flexDirection: 'column', gap: 6 }}>
        <SimpleSelect
          componentId="gsb.chat.engine"
          id="gsb-chat-engine"
          label="Ask"
          value={engine}
          disabled={busy}
          onChange={(e) => {
            setEngine(e.target.value as GenieEngine);
            refresh();
          }}
        >
          <SimpleSelectOption value="space">{ENGINE.space}: the space, with follow-ups</SimpleSelectOption>
          <SimpleSelectOption value="one">{ENGINE.one}: each question alone</SimpleSelectOption>
        </SimpleSelect>
        <Typography.Text color="secondary" size="sm">
          {info?.sandboxView
            ? `Genie reads the sandbox view of version ${info.version}, as you. The app stores no question or answer.`
            : 'Validate the design before you ask Genie.'}
          {info?.sandboxView &&
            engine === 'space' &&
            !info.space &&
            ' Create the Genie space first: Optimize, Test with Genie.'}
        </Typography.Text>
      </div>
      <div
        role="log"
        aria-label="Genie conversation"
        style={{ flex: 1, overflow: 'auto', padding: '0 16px', display: 'flex', flexDirection: 'column', gap: 16 }}
      >
        {turns.map((t, i) => (
          // Turns have no id, and the list only grows until New chat.
          // eslint-disable-next-line react/no-array-index-key
          <section key={i} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <Typography.Text bold>
              {t.question}{' '}
              <Typography.Text color="secondary" size="sm">
                ({ENGINE[t.engine]})
              </Typography.Text>
            </Typography.Text>
            {t.answer || t.error ? (
              <Answer turn={t} onTest={() => openAsTest(t)} onAsk={ask} />
            ) : (
              <div role="status">
                <Typography.Text color="secondary">Genie is working. This can take a minute.</Typography.Text>
              </div>
            )}
          </section>
        ))}
      </div>
      <form
        style={{ display: 'flex', gap: 8, padding: 16, borderTop: '1px solid var(--db-border-base)' }}
        onSubmit={(e) => {
          e.preventDefault();
          ask(question);
        }}
      >
        <Input
          componentId="gsb.chat.question"
          aria-label="Question for Genie"
          placeholder={conversationId && engine === 'space' ? 'Ask a follow-up' : 'Ask a question about the data'}
          maxLength={1000}
          disabled={!ready}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
        />
        <Button
          componentId="gsb.chat.send"
          type="primary"
          htmlType="submit"
          icon={<SendIcon />}
          aria-label="Ask"
          loading={busy}
          disabled={!ready || question.trim().length < 3}
        />
      </form>
    </aside>
  );
}
