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
import { intakeSchema, UC_TABLE_NAME } from '../../../shared/brief';
import type { BriefVersion, IntakeInput, ProjectDetail } from '../../../shared/brief';
import { api, useResource } from '../api';
import { DataState } from '../components/DataState';

interface IntakeFields {
  goal: string;
  audience: string;
  questions: string;
  terms: string;
  sources: string;
}

function toInput(f: IntakeFields): IntakeInput {
  return {
    goal: f.goal,
    audience: f.audience || undefined,
    questions: f.questions || undefined,
    terms: f.terms || undefined,
    sources: f.sources
      .split(/[\s,]+/)
      .map((s) => s.trim())
      .filter(Boolean),
  };
}

function TextField(props: {
  id: string;
  label: string;
  hint?: string;
  required?: boolean;
  multiline?: boolean;
  value: string;
  error?: string;
  onChange: (v: string) => void;
}) {
  const common = {
    componentId: `gsb.intake.${props.id}`,
    id: `gsb-intake-${props.id}`,
    value: props.value,
    'aria-invalid': props.error ? true : undefined,
    onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => props.onChange(e.target.value),
  };
  return (
    <div>
      <FormUI.Label htmlFor={common.id} required={props.required}>
        {props.label}
      </FormUI.Label>
      {props.hint && <FormUI.Hint>{props.hint}</FormUI.Hint>}
      {props.multiline ? <Input.TextArea {...common} autoSize={{ minRows: 3, maxRows: 8 }} /> : <Input {...common} />}
      {props.error && <FormUI.Message type="error" message={props.error} />}
    </div>
  );
}

function IntakeForm({ projectId, onDrafted }: { projectId: string; onDrafted: (b: BriefVersion) => void }) {
  const [f, setF] = useState<IntakeFields>({ goal: '', audience: '', questions: '', terms: '', sources: '' });
  const [errors, setErrors] = useState<Partial<Record<keyof IntakeFields, string>>>({});
  const [submitError, setSubmitError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const set = (key: keyof IntakeFields) => (v: string) => setF((prev) => ({ ...prev, [key]: v }));

  const submit = () => {
    const input = toInput(f);
    const parsed = intakeSchema.safeParse(input);
    const bad = input.sources.filter((s) => !UC_TABLE_NAME.test(s));
    if (!parsed.success || bad.length) {
      const goal = parsed.success ? undefined : parsed.error.issues.find((i) => i.path[0] === 'goal')?.message;
      setErrors({ goal, sources: bad.length ? `Use catalog.schema.table: ${bad.join(', ')}` : undefined });
      return;
    }
    setErrors({});
    setSubmitError(undefined);
    setBusy(true);
    api<BriefVersion>(`/api/projects/${projectId}/briefs`, parsed.data).then(onDrafted, (err: unknown) => {
      setSubmitError((err as Error).message);
      setBusy(false);
    });
  };

  return (
    <form
      style={{ display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 720 }}
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <TextField
        id="goal"
        label="What do you want to measure, and why?"
        required
        multiline
        value={f.goal}
        error={errors.goal}
        onChange={set('goal')}
      />
      <TextField
        id="audience"
        label="Who will use it?"
        hint="For example: finance analysts, regional sales managers."
        value={f.audience}
        onChange={set('audience')}
      />
      <TextField
        id="questions"
        label="Key questions"
        hint="One per line."
        multiline
        value={f.questions}
        onChange={set('questions')}
      />
      <TextField id="terms" label="Business terms and definitions" multiline value={f.terms} onChange={set('terms')} />
      <TextField
        id="sources"
        label="Candidate source tables"
        hint="catalog.schema.table, separated by spaces, commas or new lines."
        multiline
        value={f.sources}
        error={errors.sources}
        onChange={set('sources')}
      />
      {submitError && <Alert componentId="gsb.intake.error" type="error" closable={false} message={submitError} />}
      <div>
        <Button componentId="gsb.intake.generate" type="primary" htmlType="submit" loading={busy}>
          {busy ? 'Drafting the brief' : 'Generate brief'}
        </Button>
      </div>
    </form>
  );
}

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

function BriefView({ version }: { version: BriefVersion }) {
  const b = version.brief;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 960 }}>
      <Section title={b.title}>
        <Typography.Paragraph withoutMargins>{b.businessGoal}</Typography.Paragraph>
      </Section>
      <Section title="Audience">
        <List items={b.audience} empty="Not specified" />
      </Section>
      <Section title="Key questions">
        <List items={b.keyQuestions} />
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
      <BriefView version={version} />
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
  const [startOver, setStartOver] = useState(false);
  const setBrief = (brief: BriefVersion) => {
    if (detail.data) detail.setData({ ...detail.data, brief });
    setStartOver(false);
  };

  return (
    <DataState status={detail.status} message={detail.error} onRetry={detail.reload}>
      {detail.data && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Typography.Text color="secondary">{detail.data.project.name}</Typography.Text>
          {detail.data.brief && !startOver ? (
            <BriefPanel
              projectId={projectId}
              version={detail.data.brief}
              onChange={setBrief}
              onStartOver={() => setStartOver(true)}
            />
          ) : (
            <IntakeForm projectId={projectId} onDrafted={setBrief} />
          )}
        </div>
      )}
    </DataState>
  );
}
