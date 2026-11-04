import { useEffect, useRef, useState } from 'react';
import { Alert, Avatar, Button, Input, SparkleIcon, Spinner, Typography } from '@databricks/design-system';
import type { BriefVersion, ChatMessage, IntakeReply, SemanticBrief } from '../../../shared/brief';
import { api } from '../api';

const OPENING: ChatMessage = {
  role: 'assistant',
  content:
    'Hi! I will help you write the brief for this metric view, one question at a time. What business decision should it support? You can mention tables as @catalog.schema.table.',
};

/** The @catalog.schema.table token the cursor is in, if any. */
function mentionAt(text: string, cursor: number) {
  const m = /@([A-Za-z0-9_.-]*)$/.exec(text.slice(0, cursor));
  return m ? { start: cursor - m[0].length, parts: m[1].split('.') } : null;
}

function mentionPath(parts: string[] | null): string | null {
  if (!parts || parts.length > 3) return null;
  const [catalog = '', schema = ''] = parts;
  const q = encodeURIComponent;
  return [
    '/api/uc/catalogs?purpose=browse',
    `/api/uc/schemas?purpose=browse&catalog=${q(catalog)}`,
    `/api/uc/tables?catalog=${q(catalog)}&schema=${q(schema)}`,
  ][parts.length - 1];
}

function useMentionOptions(parts: string[] | null) {
  const [loaded, setLoaded] = useState<{ path: string; options: string[] }>({ path: '', options: [] });
  const path = mentionPath(parts);
  useEffect(() => {
    if (!path) return;
    let live = true;
    api<(string | { name: string })[]>(path).then(
      (rows) => live && setLoaded({ path, options: rows.map((r) => (typeof r === 'string' ? r : r.name)) }),
      () => live && setLoaded({ path, options: [] })
    );
    return () => {
      live = false;
    };
  }, [path]);
  const typed = parts?.[parts.length - 1]?.toLowerCase() ?? '';
  const options = path && loaded.path === path ? loaded.options : [];
  return {
    level: parts ? parts.length - 1 : -1,
    options: options.filter((o) => o.toLowerCase().startsWith(typed)).slice(0, 8),
  };
}

function Bubble({ message }: { message: ChatMessage }) {
  const mine = message.role === 'user';
  return (
    <div
      style={{ display: 'flex', gap: 8, justifyContent: mine ? 'flex-end' : 'flex-start', alignItems: 'flex-start' }}
    >
      {!mine && <Avatar type="entity" size="sm" icon={<SparkleIcon />} label="AI advisor" />}
      <div
        style={{
          maxWidth: '80%',
          padding: '8px 12px',
          borderRadius: 8,
          whiteSpace: 'pre-wrap',
          background: mine ? 'var(--db-accent-surface-subtle)' : 'var(--db-background-secondary)',
          border: '1px solid var(--db-border-base)',
        }}
      >
        <Typography.Text>{message.content}</Typography.Text>
      </div>
    </div>
  );
}

export function IntakeChat({
  projectId,
  onDraft,
  onSaved,
}: {
  projectId: string;
  onDraft: (brief: Partial<SemanticBrief>) => void;
  onSaved: (b: BriefVersion) => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([OPENING]);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [ready, setReady] = useState(false);
  const [text, setText] = useState('');
  const [cursor, setCursor] = useState(0);
  const [busy, setBusy] = useState<'chat' | 'save'>();
  const [error, setError] = useState<string>();
  const end = useRef<HTMLDivElement>(null);
  const mention = mentionAt(text, cursor);
  const { level, options } = useMentionOptions(mention?.parts ?? null);

  // Block body: scrollIntoView can return a promise, which React would call as a cleanup.
  useEffect(() => {
    void end.current?.scrollIntoView({ block: 'nearest' });
  }, [messages, busy]);

  const send = (content: string) => {
    if (!content.trim() || busy) return;
    const next = [...messages, { role: 'user' as const, content: content.trim() }];
    setMessages(next);
    setText('');
    setSuggestions([]);
    setBusy('chat');
    setError(undefined);
    // The opening message is static; the model sees the conversation after it.
    api<IntakeReply>(`/api/projects/${projectId}/intake/chat`, { messages: next.slice(1) }).then(
      (r) => {
        setBusy(undefined);
        setMessages([...next, { role: 'assistant', content: r.reply }]);
        setSuggestions(r.suggestions);
        setReady(r.ready);
        onDraft(r.brief);
      },
      (err: unknown) => {
        setBusy(undefined);
        setError((err as Error).message);
      }
    );
  };

  const save = () => {
    setBusy('save');
    setError(undefined);
    api<BriefVersion>(`/api/projects/${projectId}/intake/save`, { messages: messages.slice(1) }).then(
      onSaved,
      (err: unknown) => {
        setBusy(undefined);
        setError((err as Error).message);
      }
    );
  };

  const pick = (option: string) => {
    if (!mention) return;
    const head = [...mention.parts.slice(0, -1), option].join('.');
    const token = `@${head}${level < 2 ? '.' : ' '}`;
    const value = text.slice(0, mention.start) + token + text.slice(cursor);
    setText(value);
    setCursor(mention.start + token.length);
  };

  const answered = messages.some((m) => m.role === 'user');

  return (
    <section aria-label="Guided intake" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div
        role="log"
        aria-live="polite"
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
          padding: 16,
          minHeight: 360,
          maxHeight: '60vh',
          overflowY: 'auto',
          border: '1px solid var(--db-border-base)',
          borderRadius: 8,
        }}
      >
        {messages.map((m, i) => (
          <Bubble key={i} message={m} />
        ))}
        {busy === 'chat' && <Spinner label="The advisor is thinking" />}
        <div ref={end} />
      </div>
      {suggestions.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }} aria-label="Suggested answers">
          {suggestions.map((s) => (
            <Button key={s} componentId="gsb.intake.suggestion" size="small" onClick={() => send(s)} disabled={!!busy}>
              {s}
            </Button>
          ))}
        </div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <Input.TextArea
          componentId="gsb.intake.chat_input"
          aria-label="Your answer"
          placeholder="Type your answer. Use @ to mention a catalog, schema or table."
          value={text}
          autoSize={{ minRows: 2, maxRows: 6 }}
          maxLength={4000}
          onChange={(e) => {
            setText(e.target.value);
            setCursor(e.target.selectionStart);
          }}
          onSelect={(e) => setCursor(e.currentTarget.selectionStart)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !mention) {
              e.preventDefault();
              send(text);
            }
          }}
        />
        {mention && options.length > 0 && (
          <div role="listbox" aria-label="Unity Catalog names" style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {options.map((o) => (
              <Button key={o} componentId="gsb.intake.mention" size="small" type="tertiary" onClick={() => pick(o)}>
                {['Catalog', 'Schema', 'Table'][level]}: {o}
              </Button>
            ))}
          </div>
        )}
      </div>
      {error && <Alert componentId="gsb.intake.error" type="error" closable={false} message={error} />}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <Button
          componentId="gsb.intake.send"
          type="primary"
          onClick={() => send(text)}
          disabled={!text.trim() || !!busy}
        >
          Send
        </Button>
        <Button
          componentId="gsb.intake.save"
          type={ready ? 'primary' : undefined}
          loading={busy === 'save'}
          disabled={!answered || !!busy}
          onClick={save}
        >
          Save brief draft
        </Button>
        <Typography.Text color="secondary">
          {ready
            ? 'The brief has what it needs. Save it, or keep refining.'
            : 'Save at any time. Gaps become open questions.'}
        </Typography.Text>
      </div>
    </section>
  );
}
