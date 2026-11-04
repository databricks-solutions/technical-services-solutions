import { useState } from 'react';
import type { ReactNode } from 'react';
import { useParams } from 'react-router';
import {
  Alert,
  Button,
  FormUI,
  Input,
  Table,
  TableCell,
  TableHeader,
  TableRow,
  Tag,
  Typography,
} from '@databricks/design-system';
import type { BriefVersion, ProjectDetail, SemanticBrief } from '../../../shared/brief';
import { api, useResource } from '../api';
import { DataState } from '../components/DataState';
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
      </Section>
      <Section title="Dimensions">
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
  const [busy, setBusy] = useState<'refine' | 'confirm'>();
  const [error, setError] = useState<string>();
  const confirmed = version.status === 'confirmed';

  const run = (kind: 'refine' | 'confirm', path: string, body: unknown) => {
    setBusy(kind);
    setError(undefined);
    api<BriefVersion>(path, body).then(
      (b) => {
        setBusy(undefined);
        setInstruction('');
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
      <Alert
        componentId="gsb.brief.ai_notice"
        type="info"
        closable={false}
        message="Generated by AI. Review every section before you confirm."
        description={version.summary}
      />
      <BriefView brief={version.brief} />
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
          <Button componentId="gsb.brief.start_over" disabled={!!busy} onClick={onStartOver}>
            Start over
          </Button>
        </div>
      </div>
    </div>
  );
}

export function IntakePage() {
  const { projectId = '' } = useParams();
  const detail = useResource<ProjectDetail>(`/api/projects/${projectId}`);
  const [chatting, setChatting] = useState(false);
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
            }}
          />
        ) : (
          <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start', flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 480px', minWidth: 360 }}>
              <IntakeChat projectId={projectId} onDraft={setDraft} onSaved={setBrief} />
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
              <BriefView brief={draft} />
            </aside>
          </div>
        ))}
    </DataState>
  );
}
