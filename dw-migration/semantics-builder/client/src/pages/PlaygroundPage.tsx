import { useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router';
import {
  Alert,
  Button,
  Input,
  Modal,
  NavList,
  Table,
  TableCell,
  TableHeader,
  TableRow,
  Tag,
  Typography,
} from '@databricks/design-system';
import type { Pattern, PatternFit, PatternPlan, PatternRun } from '../../../shared/patterns';
import { api, useResource } from '../api';
import { OpenInCatalog } from '../components/OpenInCatalog';
import { DataState } from '../components/DataState';
import { SqlBlock } from '../components/SqlBlock';

const UPSTREAM = 'https://github.com/databricks-solutions/uc-semantics-patterns';

// Upstream categories first, then the extended ones. Unknown categories go last.
const CATEGORY_ORDER = [
  'Time intelligence',
  'Semi-additive',
  'Ranking',
  'Currency conversion',
  'Segmentation',
  'Calendars',
  'Modeling',
  'Measures',
  'Planning',
  'Customer analytics',
];
const rank = (c: string) => (CATEGORY_ORDER.includes(c) ? CATEGORY_ORDER.indexOf(c) : CATEGORY_ORDER.length);

const RUN_TAG: Record<PatternRun['status'], { color: 'teal' | 'coral' | 'lemon'; label: string }> = {
  passed: { color: 'teal', label: 'Matches the expected output' },
  failed: { color: 'coral', label: 'Failed' },
  running: { color: 'lemon', label: 'Running' },
};

/** Dates at midnight UTC come back as timestamps; show the date only. */
const cell = (v: string | null) =>
  v === null ? 'null' : /^\d{4}-\d{2}-\d{2}T00:00:00(\.0+)?Z$/.test(v) ? v.slice(0, 10) : v;

function ExpectedTable({ pattern }: { pattern: Pattern }) {
  const { columns, rows } = pattern.expected;
  return (
    <div style={{ overflowX: 'auto' }}>
      <Table aria-label={`Expected output of ${pattern.title}`} scrollable>
        <TableRow isHeader>
          {columns.map((c) => (
            <TableHeader key={c} componentId="gsb.playground.expected_header">
              {c}
            </TableHeader>
          ))}
        </TableRow>
        {rows.map((r, i) => (
          <TableRow key={i}>
            {r.map((v, j) => (
              <TableCell key={j}>{cell(v)}</TableCell>
            ))}
          </TableRow>
        ))}
      </Table>
    </div>
  );
}

/** Shows the exact SQL, runs it only after the user approves it. */
function ApproveSql({
  title,
  statements,
  okText,
  busy,
  onOk,
  onCancel,
}: {
  title: string;
  statements: string[];
  okText: string;
  busy: boolean;
  onOk: () => void;
  onCancel: () => void;
}) {
  return (
    <Modal
      componentId="gsb.playground.approve"
      title={title}
      visible
      okText={okText}
      cancelText="Cancel"
      confirmLoading={busy}
      onOk={onOk}
      onCancel={onCancel}
      size="wide"
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <Typography.Text>This runs as you, in the sandbox schema. Read it before you approve.</Typography.Text>
        {statements.map((s) => (
          <SqlBlock key={s} label="SQL to run" sql={s} />
        ))}
      </div>
    </Modal>
  );
}

const role = (r: string) => r.replace(/_/g, ' ');

/** Rule-based: matches the pattern roles to source columns by type and name. */
function FitNotice({ fit, assessed }: { fit: PatternFit | undefined; assessed: boolean }) {
  const { projectId = '', parentId = '' } = useParams();
  const navigate = useNavigate();
  if (!assessed || !fit)
    return (
      <Alert
        componentId="gsb.playground.fit_unknown"
        type="info"
        closable={false}
        message="Assess your sources to see if this pattern fits your data."
        description={
          <Button
            componentId="gsb.playground.fit_assess"
            size="small"
            onClick={() => void navigate(`/projects/${parentId}/sub/${projectId}/sources`)}
          >
            Open Sources & Readiness
          </Button>
        }
      />
    );
  const found = fit.found.map((f) => `${role(f.role)}: ${f.match}`).join('; ');
  const missing = fit.missing.map(role).join(', ');
  return (
    <Alert
      componentId="gsb.playground.fit"
      type={fit.status === 'fits' ? 'success' : 'warning'}
      closable={false}
      message={
        fit.status === 'fits'
          ? 'Fits your sources'
          : fit.status === 'partial'
            ? `Partly fits. Missing: ${missing}`
            : `Does not fit yet. Missing: ${missing}`
      }
      description={found ? `Found ${found}. Checked by rules on column names and types, not by AI.` : undefined}
    />
  );
}

function PatternDetail({
  pattern,
  run,
  fit,
  assessed,
  onRun,
}: {
  pattern: Pattern;
  run: PatternRun | undefined;
  fit: PatternFit | undefined;
  assessed: boolean;
  onRun: (run: PatternRun) => void;
}) {
  const { projectId = '', parentId = '' } = useParams();
  const base = `/api/projects/${projectId}/patterns/${pattern.slug}/try`;
  const [approve, setApprove] = useState<{ kind: 'try' | 'drop'; statements: string[] }>();
  const [busy, setBusy] = useState(false);
  const [removed, setRemoved] = useState(false);
  const [error, setError] = useState<string>();
  const [applying, setApplying] = useState(false);
  const navigate = useNavigate();

  const apply = () => {
    setError(undefined);
    setApplying(true);
    api(`/api/projects/${projectId}/patterns/${pattern.slug}/apply`, {}).then(
      () => void navigate(`/projects/${parentId}/sub/${projectId}/designer`),
      (err: unknown) => {
        setApplying(false);
        setError((err as Error).message);
      }
    );
  };

  const fail = (err: unknown) => {
    setBusy(false);
    setError((err as Error).message);
  };
  const review = () => {
    setError(undefined);
    setBusy(true);
    api<PatternPlan>(base).then((plan) => {
      setBusy(false);
      setApprove({ kind: 'try', statements: plan.statements });
    }, fail);
  };
  const confirm = () => {
    if (!approve) return;
    setBusy(true);
    const done = () => {
      setBusy(false);
      setApprove(undefined);
    };
    if (approve.kind === 'try')
      api<PatternRun>(base, { statements: approve.statements }).then((r) => {
        done();
        setRemoved(false);
        onRun(r);
      }, fail);
    else
      api(`${base}/drop`, { statements: approve.statements }).then(() => {
        done();
        setRemoved(true);
      }, fail);
  };

  return (
    <article aria-labelledby="gsb-pattern-title" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <Typography.Title level={3} id="gsb-pattern-title" withoutMargins>
          {pattern.title}
        </Typography.Title>
        <Tag componentId="gsb.playground.category">{pattern.category}</Tag>
        {pattern.minDbr && <Tag componentId="gsb.playground.dbr">Needs DBR {pattern.minDbr} or above</Tag>}
      </div>
      <Typography.Paragraph withoutMargins>{pattern.scenario}</Typography.Paragraph>
      <div>
        <Typography.Text bold>Sample question: </Typography.Text>
        <Typography.Text>{pattern.question}</Typography.Text>
      </div>
      <FitNotice fit={fit} assessed={assessed} />

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <Button
          componentId="gsb.playground.try"
          type={fit?.status === 'fits' ? undefined : 'primary'}
          loading={busy && !approve}
          onClick={review}
        >
          Try in sandbox
        </Button>
        <Button
          componentId="gsb.playground.apply"
          type={fit?.status === 'fits' ? 'primary' : undefined}
          loading={applying}
          disabled={busy}
          onClick={apply}
        >
          Apply to my data
        </Button>
        {run && run.cleanup.length > 0 && !removed && (
          <Button
            componentId="gsb.playground.drop"
            disabled={busy}
            onClick={() => setApprove({ kind: 'drop', statements: run.cleanup })}
          >
            Remove sandbox view
          </Button>
        )}
      </div>
      {applying && (
        <div role="status">
          <Typography.Text color="secondary">
            Reading your tables and adapting the pattern. This can take a minute. The result opens in the Metric
            Designer as a new version.
          </Typography.Text>
        </div>
      )}
      {error && <Alert componentId="gsb.playground.error" type="error" closable={false} message={error} />}
      {run && (
        <div role="status" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <Typography.Text bold>Last run</Typography.Text>
            <Tag componentId="gsb.playground.run_status" color={RUN_TAG[run.status].color}>
              {RUN_TAG[run.status].label}
            </Tag>
            <Typography.Text color="secondary">
              {run.sandboxView}, by {run.createdBy}, {new Date(run.createdAt).toLocaleString()}{' '}
              <OpenInCatalog fullName={run.sandboxView} label="Open the sandbox view" />
            </Typography.Text>
          </div>
          {run.detail && <Typography.Text>{run.detail}</Typography.Text>}
          {removed && <Typography.Text color="secondary">The sandbox view is removed.</Typography.Text>}
        </div>
      )}

      <SqlBlock label="Metric view YAML" sql={pattern.yaml} />
      <SqlBlock label="Test query" sql={pattern.test.query.replaceAll('{{view}}', '<sandbox view>')} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <Typography.Text bold>Expected output on the sample data</Typography.Text>
        <ExpectedTable pattern={pattern} />
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <Typography.Text bold>Columns to map to your data</Typography.Text>
        <ul style={{ margin: 0, paddingLeft: 20 }}>
          {pattern.roles.map((r) => (
            <li key={r.name}>
              <code>{r.name}</code>: {r.description}
            </li>
          ))}
        </ul>
      </div>

      {approve && (
        <ApproveSql
          title={approve.kind === 'try' ? 'Create the pattern view in the sandbox' : 'Remove the sandbox view'}
          statements={approve.statements}
          okText="Run SQL"
          busy={busy}
          onOk={confirm}
          onCancel={() => setApprove(undefined)}
        />
      )}
    </article>
  );
}

export function PlaygroundPage() {
  const { projectId = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const [filter, setFilter] = useState('');
  const patterns = useResource<Pattern[]>('/api/patterns');
  const runs = useResource<PatternRun[]>(`/api/projects/${projectId}/patterns/runs`);
  const fits = useResource<PatternFit[]>(`/api/projects/${projectId}/patterns/fit`);
  const fitOf = (slug: string) => fits.data?.find((f) => f.slug === slug);
  const list = patterns.data ?? [];
  const needle = filter.trim().toLowerCase();
  const shown = list.filter((p) =>
    [p.title, p.category, p.scenario, p.question].some((t) => t.toLowerCase().includes(needle))
  );
  const categories = [...new Set(shown.map((p) => p.category))].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
  const selected =
    list.find((p) => p.slug === params.get('pattern')) ?? shown.find((p) => p.category === categories[0]);

  return (
    <DataState
      status={patterns.status === 'ready' && !list.length ? 'empty' : patterns.status}
      message={patterns.error ?? (patterns.status === 'ready' ? 'No patterns are installed.' : undefined)}
      onRetry={patterns.reload}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <Typography.Paragraph withoutMargins color="secondary">
          Proven metric view patterns on sample data. Try one in the sandbox, then adapt it to your sources. Categories
          follow{' '}
          <Typography.Link componentId="gsb.playground.upstream" href={UPSTREAM} openInNewTab>
            uc-semantics-patterns
          </Typography.Link>
          .
        </Typography.Paragraph>
        <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start', flexWrap: 'wrap' }}>
          <nav aria-label="Patterns" style={{ width: 280, display: 'flex', flexDirection: 'column', gap: 12 }}>
            <Input
              componentId="gsb.playground.filter"
              aria-label="Filter patterns"
              placeholder="Filter patterns"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              allowClear
            />
            {!shown.length && <Typography.Text color="secondary">No pattern matches the filter.</Typography.Text>}
            <NavList.Root aria-label="Pattern list">
              {categories.map((c) => (
                <NavList.Group key={c}>
                  <NavList.GroupLabel>{c}</NavList.GroupLabel>
                  <NavList.GroupContent>
                    <NavList.List style={{ paddingLeft: 16 }}>
                      {shown
                        .filter((p) => p.category === c)
                        .map((p) => {
                          const run = runs.data?.find((r) => r.slug === p.slug);
                          return (
                            <NavList.Item key={p.slug}>
                              <NavList.Link
                                href={`?pattern=${p.slug}`}
                                active={p.slug === selected?.slug}
                                label={p.title}
                                onClick={(e) => {
                                  e.preventDefault();
                                  setParams({ pattern: p.slug });
                                }}
                              />
                              {fitOf(p.slug)?.status === 'fits' && <NavList.Badge>Fits</NavList.Badge>}
                              {run?.status === 'passed' && <NavList.Badge>Passed</NavList.Badge>}
                              {run?.status === 'failed' && <NavList.Badge>Failed</NavList.Badge>}
                            </NavList.Item>
                          );
                        })}
                    </NavList.List>
                  </NavList.GroupContent>
                </NavList.Group>
              ))}
            </NavList.Root>
          </nav>
          <div style={{ flex: 1, minWidth: 320 }}>
            {selected && (
              <PatternDetail
                key={selected.slug}
                pattern={selected}
                run={runs.data?.find((r) => r.slug === selected.slug)}
                fit={fitOf(selected.slug)}
                assessed={!!fits.data?.length}
                onRun={(r) => runs.setData([...(runs.data ?? []).filter((x) => x.slug !== r.slug), r])}
              />
            )}
          </div>
        </div>
      </div>
    </DataState>
  );
}
