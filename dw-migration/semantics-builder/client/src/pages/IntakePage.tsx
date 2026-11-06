import { useState } from 'react';
import type { ReactNode } from 'react';
import { useNavigate, useParams } from 'react-router';
import {
  Alert,
  Button,
  FormUI,
  Input,
  Table,
  TrashIcon,
  TableCell,
  TableHeader,
  TableRow,
  Tag,
  Typography,
} from '@databricks/design-system';
import { IMPORTED_SUMMARY, MANUAL_SUMMARY } from '../../../shared/brief';
import type { BriefVersion, IntakeContext, MemoryItem, ProjectDetail, SemanticBrief } from '../../../shared/brief';
import { api, useResource } from '../api';
import { DataState } from '../components/DataState';
import { BriefEditor } from '../components/BriefEditor';
import { IntakeChat } from '../components/IntakeChat';

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <Typography.Title level={4} withoutMargins>
        {title}
      </Typography.Title>
      {children}
    </section>
  );
}

function List({ items, empty = 'None' }: { items: string[]; empty?: string }) {
  if (!items.length) return <Typography.Text color="secondary">{empty}</Typography.Text>;
  return (
    <ul style={{ margin: 0, paddingLeft: 20 }}>
      {items.map((i) => (
        <li key={i}>
          <Typography.Text>{i}</Typography.Text>
        </li>
      ))}
    </ul>
  );
}

const EMPTY: SemanticBrief = {
  title: '',
  businessGoal: '',
  audience: [],
  keyQuestions: [],
  measures: [],
  dimensions: [],
  timeGrains: [],
  candidateSources: [],
  glossary: [],
  assumptions: [],
  openQuestions: [],
};

function BriefView({ brief }: { brief: Partial<SemanticBrief> }) {
  const b = { ...EMPTY, ...brief };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 960 }}>
      <Section title={b.title || 'Untitled brief'}>
        <Typography.Paragraph withoutMargins>{b.businessGoal || 'The goal is not defined yet.'}</Typography.Paragraph>
      </Section>
      <Section title="Audience">
        <List items={b.audience} empty="Not specified" />
      </Section>
      <Section title="Key questions">
        <List items={b.keyQuestions} empty="Not defined yet" />
      </Section>
      <Section title="Measures">
        {!b.measures.length ? (
          <Typography.Text color="secondary">None yet</Typography.Text>
        ) : (
          <Table>
            <TableRow isHeader>
              <TableHeader componentId="gsb.brief.measure_name">Name</TableHeader>
              <TableHeader componentId="gsb.brief.measure_agg">Aggregation</TableHeader>
              <TableHeader componentId="gsb.brief.measure_desc">Description</TableHeader>
            </TableRow>
            {b.measures.map((m) => (
              <TableRow key={m.name}>
                <TableCell>{m.name}</TableCell>
                <TableCell>{m.aggregation.replace('_', ' ')}</TableCell>
                <TableCell>{m.description}</TableCell>
              </TableRow>
            ))}
          </Table>
        )}
      </Section>
      <Section title="Dimensions">
        {!b.dimensions.length ? (
          <Typography.Text color="secondary">None yet</Typography.Text>
        ) : (
          <Table>
            <TableRow isHeader>
              <TableHeader componentId="gsb.brief.dim_name">Name</TableHeader>
              <TableHeader componentId="gsb.brief.dim_desc">Description</TableHeader>
            </TableRow>
            {b.dimensions.map((d) => (
              <TableRow key={d.name}>
                <TableCell>{d.name}</TableCell>
                <TableCell>{d.description}</TableCell>
              </TableRow>
            ))}
          </Table>
        )}
      </Section>
      <Section title="Time grains">
        <div style={{ display: 'flex', gap: 4 }}>
          {b.timeGrains.length
            ? b.timeGrains.map((g) => (
                <Tag componentId="gsb.brief.grain" key={g}>
                  {g}
                </Tag>
              ))
            : 'None'}
        </div>
      </Section>
      <Section title="Candidate sources">
        <List items={b.candidateSources} empty="No tables named yet" />
      </Section>
      <Section title="Glossary">
        <List items={b.glossary.map((g) => `${g.term}: ${g.definition}`)} />
      </Section>
      <Section title="Assumptions">
        <List items={b.assumptions} />
      </Section>
      <Section title="Open questions">
        <List items={b.openQuestions} />
      </Section>
    </div>
  );
}

function BriefPanel({
  projectId,
  version,
  onChange,
  onStartOver,
}: {
  projectId: string;
  version: BriefVersion;
  onChange: (b: BriefVersion) => void;
  onStartOver: () => void;
}) {
  const [instruction, setInstruction] = useState('');
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState<'refine' | 'confirm' | 'edit'>();
  const [error, setError] = useState<string>();
  const confirmed = version.status === 'confirmed';
  const SECTIONS = {
    keyQuestions: 'key questions',
    measures: 'measures',
    dimensions: 'dimensions',
    timeGrains: 'time grains',
    candidateSources: 'candidate sources',
    glossary: 'glossary',
  } as const;
  const empty = confirmed
    ? []
    : Object.entries(SECTIONS).flatMap(([k, label]) =>
        version.brief[k as keyof typeof SECTIONS].length ? [] : [label]
      );

  const run = (kind: 'refine' | 'confirm' | 'edit', path: string, body: unknown) => {
    setBusy(kind);
    setError(undefined);
    api<BriefVersion>(path, body).then(
      (b) => {
        setBusy(undefined);
        setInstruction('');
        setEditing(false);
        onChange(b);
      },
      (err: unknown) => {
        setBusy(undefined);
        setError((err as Error).message);
      }
    );
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Typography.Text bold>Version {version.version}</Typography.Text>
        <Tag componentId="gsb.brief.status" color={confirmed ? 'teal' : 'lemon'}>
          {confirmed ? 'Confirmed' : 'Draft'}
        </Tag>
      </div>
      {version.summary === MANUAL_SUMMARY || version.summary === IMPORTED_SUMMARY ? (
        <Alert componentId="gsb.brief.manual_notice" type="info" closable={false} message={version.summary} />
      ) : (
        <Alert
          componentId="gsb.brief.ai_notice"
          type="info"
          closable={false}
          message="Generated by AI. Review every section before you confirm."
          description={version.summary}
        />
      )}
      {editing ? (
        <BriefEditor
          initial={version.brief}
          saving={busy === 'edit'}
          onCancel={() => setEditing(false)}
          onSave={(brief) => run('edit', `/api/projects/${projectId}/briefs/edit`, { brief })}
        />
      ) : (
        <BriefView brief={version.brief} />
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxWidth: 720 }}>
        <FormUI.Label htmlFor="gsb-brief-refine">Ask for a change</FormUI.Label>
        <Input.TextArea
          componentId="gsb.brief.refine_input"
          id="gsb-brief-refine"
          value={instruction}
          autoSize={{ minRows: 2, maxRows: 6 }}
          placeholder="For example: add a gross margin measure and drop the weekly grain."
          onChange={(e) => setInstruction(e.target.value)}
        />
        {error && <Alert componentId="gsb.brief.error" type="error" closable={false} message={error} />}
        <div style={{ display: 'flex', gap: 8 }}>
          <Button
            componentId="gsb.brief.refine"
            loading={busy === 'refine'}
            disabled={instruction.trim().length < 3 || !!busy}
            onClick={() => run('refine', `/api/projects/${projectId}/briefs/refine`, { instruction })}
          >
            Apply change
          </Button>
          <Button
            componentId="gsb.brief.confirm"
            type="primary"
            loading={busy === 'confirm'}
            disabled={confirmed || !!busy}
            onClick={() => run('confirm', `/api/projects/${projectId}/briefs/${version.version}/confirm`, {})}
          >
            {confirmed ? 'Brief confirmed' : 'Confirm brief'}
          </Button>
          <Button componentId="gsb.brief.edit" disabled={!!busy || editing} onClick={() => setEditing(true)}>
            Edit by hand
          </Button>
          {empty.length > 0 && !editing && (
            <Button
              componentId="gsb.brief.suggest"
              loading={busy === 'refine'}
              disabled={!!busy}
              onClick={() =>
                run('refine', `/api/projects/${projectId}/briefs/refine`, {
                  instruction: `Suggest content for the empty sections: ${empty.join(', ')}. Keep the other sections.`,
                })
              }
            >
              Suggest the empty sections with AI
            </Button>
          )}
          <Button componentId="gsb.brief.start_over" disabled={!!busy} onClick={onStartOver}>
            Start over
          </Button>
        </div>
      </div>
    </div>
  );
}

/** Terms and assumptions confirmed in this project's sub-projects. The chat reuses them. */
function MemoryPanel({
  projectId,
  items,
  onRemoved,
}: {
  projectId: string;
  items: MemoryItem[];
  onRemoved: (id: string) => void;
}) {
  const [error, setError] = useState<string>();
  return (
    <section aria-labelledby="gsb-memory" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <Typography.Title level={4} id="gsb-memory" withoutMargins>
        Project memory ({items.length})
      </Typography.Title>
      <Typography.Text color="secondary" size="sm">
        {items.length
          ? 'Terms and assumptions from confirmed briefs in this project. The AI reuses them, so terms mean the same thing in every sub-project.'
          : 'Empty. When you confirm a brief, its terms and assumptions are saved here for the other sub-projects of this project.'}
      </Typography.Text>
      {error && <FormUI.Message type="error" message={error} />}
      {items.length > 0 && (
        <ul style={{ margin: 0, paddingLeft: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 6 }}>
          {items.map((m) => (
            <li key={m.id} style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
              <div style={{ flex: 1 }}>
                <Typography.Text bold={m.kind === 'term'}>{m.text}</Typography.Text>
                {m.detail && <Typography.Text>: {m.detail}</Typography.Text>}
                <br />
                <Typography.Text color="secondary" size="sm">
                  {m.kind === 'term' ? 'Term' : 'Assumption'}
                  {m.fromName ? ` from ${m.fromName}` : ''}
                </Typography.Text>
              </div>
              <Button
                componentId="gsb.intake.memory_remove"
                size="small"
                type="tertiary"
                icon={<TrashIcon />}
                aria-label={`Remove ${m.text} from project memory`}
                onClick={() =>
                  void api(`/api/projects/${projectId}/memory/${m.id}/remove`, {}).then(
                    () => onRemoved(m.id),
                    (err: unknown) => setError((err as Error).message)
                  )
                }
              />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function IntakePage() {
  const { projectId = '' } = useParams();
  const { parentId = '' } = useParams();
  const navigate = useNavigate();
  const detail = useResource<ProjectDetail>(`/api/projects/${projectId}`);
  const context = useResource<IntakeContext>(`/api/projects/${projectId}/intake/context`);
  const [chatting, setChatting] = useState(false);
  const [manual, setManual] = useState(false);
  const [savingManual, setSavingManual] = useState(false);
  const [manualError, setManualError] = useState<string>();
  const [draft, setDraft] = useState<Partial<SemanticBrief>>({});
  const setBrief = (brief: BriefVersion) => {
    if (detail.data) detail.setData({ ...detail.data, brief });
    setChatting(false);
  };
  const saved = detail.data?.brief;

  return (
    <DataState status={detail.status} message={detail.error} onRetry={detail.reload}>
      {detail.data &&
        (saved && !chatting ? (
          <BriefPanel
            projectId={projectId}
            version={saved}
            onChange={setBrief}
            onStartOver={() => {
              setDraft({});
              setChatting(true);
              void api(`/api/projects/${projectId}/intake/session/clear`, {}).then(() => {
                if (context.data) context.setData({ ...context.data, session: [], lastTurn: null });
              });
            }}
          />
        ) : (
          <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start', flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 480px', minWidth: 360 }}>
              <DataState status={context.status} message={context.error} onRetry={context.reload}>
                {context.data && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                    {!context.data.tables.length && (
                      <Alert
                        componentId="gsb.intake.no_sources"
                        type="info"
                        closable={false}
                        message="Choose your tables first, and the AI can suggest what to build from them."
                        action={
                          <Button
                            componentId="gsb.intake.go_sources"
                            size="small"
                            onClick={() => void navigate(`/projects/${parentId}/sub/${projectId}/sources`)}
                          >
                            Choose tables
                          </Button>
                        }
                      />
                    )}
                    {manual ? (
                      <>
                        {manualError && (
                          <Alert
                            componentId="gsb.intake.manual_error"
                            type="error"
                            closable={false}
                            message={manualError}
                          />
                        )}
                        <BriefEditor
                          initial={Object.keys(draft).length ? draft : { candidateSources: context.data.tables }}
                          saving={savingManual}
                          onCancel={() => setManual(false)}
                          onSave={(brief) => {
                            setSavingManual(true);
                            setManualError(undefined);
                            api<BriefVersion>(`/api/projects/${projectId}/briefs/edit`, { brief }).then(
                              (b) => {
                                setSavingManual(false);
                                setManual(false);
                                setBrief(b);
                              },
                              (err: unknown) => {
                                setSavingManual(false);
                                setManualError((err as Error).message);
                              }
                            );
                          }}
                        />
                      </>
                    ) : (
                      <>
                        <div>
                          <Button componentId="gsb.intake.write_by_hand" size="small" onClick={() => setManual(true)}>
                            Write the brief by hand
                          </Button>
                        </div>
                        <IntakeChat
                          key={context.data.session.length ? 'resume' : 'new'}
                          projectId={projectId}
                          context={context.data}
                          onDraft={setDraft}
                          onSaved={setBrief}
                        />
                      </>
                    )}
                  </div>
                )}
              </DataState>
            </div>
            <aside
              aria-label="Brief draft"
              style={{
                flex: '1 1 360px',
                minWidth: 320,
                padding: 16,
                border: '1px solid var(--db-border-base)',
                borderRadius: 8,
                display: 'flex',
                flexDirection: 'column',
                gap: 12,
              }}
            >
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <Typography.Title level={4} withoutMargins>
                  Brief draft
                </Typography.Title>
                <Tag componentId="gsb.intake.live">Updates as you chat</Tag>
              </div>
              <BriefView brief={Object.keys(draft).length ? draft : (context.data?.lastTurn?.brief ?? {})} />
              {context.data && (
                <MemoryPanel
                  projectId={projectId}
                  items={context.data.memory}
                  onRemoved={(id) =>
                    context.data &&
                    context.setData({ ...context.data, memory: context.data.memory.filter((m) => m.id !== id) })
                  }
                />
              )}
            </aside>
          </div>
        ))}
    </DataState>
  );
}
