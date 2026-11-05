import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import {
  Alert,
  Button,
  Checkbox,
  FormUI,
  Input,
  Modal,
  Table,
  TableCell,
  TableHeader,
  TableRow,
  Tabs,
  Tag,
  Typography,
} from '@databricks/design-system';
import type { OptimizeView, StressFlag, StressRun, WorkloadQuery } from '../../../shared/optimize';
import { api, useResource } from '../api';
import { DataState } from '../components/DataState';
import { MaterializePanel } from '../components/MaterializePanel';
import { PracticesPanel } from '../components/PracticesPanel';
import { CostPanel } from '../components/CostPanel';
import { SqlBlock } from '../components/SqlBlock';

const FLAG: Record<StressFlag, { color: 'coral' | 'lemon'; label: string }> = {
  error: { color: 'coral', label: 'Error' },
  slow: { color: 'coral', label: 'Slow' },
  spill: { color: 'lemon', label: 'Spills to disk' },
  no_pruning: { color: 'lemon', label: 'Full scan' },
};

const STATUS: Record<StressRun['status'], { color: 'indigo' | 'teal' | 'coral' | 'lemon'; label: string }> = {
  running: { color: 'indigo', label: 'Running' },
  refreshing: { color: 'indigo', label: 'Refreshing' },
  stopping: { color: 'lemon', label: 'Stopping' },
  stopped: { color: 'lemon', label: 'Stopped' },
  finished: { color: 'teal', label: 'Finished' },
  failed: { color: 'coral', label: 'Failed' },
};

const ms = (v: number | null) => (v === null ? '-' : v < 1000 ? `${Math.round(v)} ms` : `${(v / 1000).toFixed(1)} s`);
const bytes = (v: number | null) => {
  if (v === null) return '-';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let n = v;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(i ? 1 : 0)} ${units[i]}`;
};
const WRAP = { whiteSpace: 'normal', overflowWrap: 'anywhere' } as const;
const count = (v: number | null) => (v === null ? '-' : v.toLocaleString());
const sameQuery = (a: WorkloadQuery, b: WorkloadQuery) => a.label === b.label && a.origin === b.origin;

/** Pick dimensions and measures by name; the server builds the SQL. */
function AddQuery({
  dimensions,
  measures,
  onAdd,
}: {
  dimensions: string[];
  measures: string[];
  onAdd: (q: WorkloadQuery) => void;
}) {
  const [dims, setDims] = useState<string[]>([]);
  const [meas, setMeas] = useState<string[]>([]);
  const toggle = (list: string[], set: (v: string[]) => void, v: string, on: boolean) =>
    set(on ? [...list, v] : list.filter((x) => x !== v));
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        padding: 12,
        border: '1px solid var(--db-border-base)',
        borderRadius: 8,
      }}
    >
      <Typography.Text bold>Add a query</Typography.Text>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div role="group" aria-label="Dimensions" style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <Typography.Text color="secondary">Group by</Typography.Text>
          {dimensions.map((d) => (
            <Checkbox
              key={d}
              componentId="gsb.optimize.add_dim"
              isChecked={dims.includes(d)}
              onChange={(on) => toggle(dims, setDims, d, on)}
            >
              {d}
            </Checkbox>
          ))}
        </div>
        <div role="group" aria-label="Measures" style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <Typography.Text color="secondary">Measures</Typography.Text>
          {measures.map((m) => (
            <Checkbox
              key={m}
              componentId="gsb.optimize.add_measure"
              isChecked={meas.includes(m)}
              onChange={(on) => toggle(meas, setMeas, m, on)}
            >
              {m}
            </Checkbox>
          ))}
        </div>
      </div>
      <div>
        <Button
          componentId="gsb.optimize.add"
          size="small"
          disabled={!meas.length}
          onClick={() => {
            onAdd({
              label: `${meas.join(', ')}${dims.length ? ` by ${dims.join(', ')}` : ''}`.slice(0, 200),
              dimensions: dims,
              measures: meas,
              origin: 'custom',
            });
            setDims([]);
            setMeas([]);
          }}
        >
          Add to the workload
        </Button>
      </div>
    </div>
  );
}

function Results({ run, onStop, stopping }: { run: StressRun; onStop: () => void; stopping: boolean }) {
  const active = run.status === 'running' || run.status === 'stopping';
  const done = run.queries.filter((q) => q.attempts.length >= run.settings.repeats).length;
  const measured = run.queries.filter((q) => q.warmMs !== null || q.flags.includes('error'));
  const flagged = measured.filter((q) => q.flags.length).length;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <Typography.Title level={4} withoutMargins>
          Last stress test
        </Typography.Title>
        <Tag componentId="gsb.optimize.status" color={STATUS[run.status].color}>
          {STATUS[run.status].label}
        </Tag>
        <Typography.Text color="secondary">
          Version {run.version}, {done} of {run.queries.length} queries done, {run.settings.repeats} runs each, by{' '}
          {run.createdBy}, {new Date(run.createdAt).toLocaleString()}
        </Typography.Text>
        {active && (
          <Button componentId="gsb.optimize.stop" size="small" danger loading={stopping} onClick={onStop}>
            Stop
          </Button>
        )}
      </div>
      {run.error && <Alert componentId="gsb.optimize.run_error" type="error" closable={false} message={run.error} />}
      {!active && run.status !== 'failed' && (
        <Alert
          componentId="gsb.optimize.summary"
          type={flagged ? 'warning' : measured.length ? 'success' : 'info'}
          closable={false}
          message={
            !measured.length
              ? 'No query finished before the stop.'
              : flagged
                ? `${flagged} of ${measured.length} measured queries need attention.`
                : `All ${measured.length} measured queries ran under the ${ms(run.settings.targetMs)} target.`
          }
          description="Times are execution times from the Query History, with the result cache bypassed. Cold is the first run; warm is the median of the others."
        />
      )}
      <Table aria-label="Stress test results" scrollable>
        <TableRow isHeader>
          <TableHeader componentId="gsb.optimize.r_query">Query</TableHeader>
          <TableHeader componentId="gsb.optimize.r_cold">Cold</TableHeader>
          <TableHeader componentId="gsb.optimize.r_warm">Warm</TableHeader>
          <TableHeader componentId="gsb.optimize.r_max">Max</TableHeader>
          <TableHeader componentId="gsb.optimize.r_read">Read</TableHeader>
          <TableHeader componentId="gsb.optimize.r_rows">Rows read</TableHeader>
          <TableHeader componentId="gsb.optimize.r_flags">Flags</TableHeader>
        </TableRow>
        {run.queries.map((q) => (
          <TableRow key={`${q.origin}:${q.label}`}>
            <TableCell>
              <div style={WRAP}>{q.label}</div>
            </TableCell>
            <TableCell>{ms(q.coldMs)}</TableCell>
            <TableCell>{ms(q.warmMs)}</TableCell>
            <TableCell>{ms(q.maxMs)}</TableCell>
            <TableCell>{bytes(q.readBytes)}</TableCell>
            <TableCell>{count(q.rowsRead)}</TableCell>
            <TableCell>
              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                {q.attempts.length < run.settings.repeats && active ? (
                  <Typography.Text color="secondary">
                    {q.attempts.length ? `${q.attempts.length} of ${run.settings.repeats}` : 'Waiting'}
                  </Typography.Text>
                ) : q.flags.length ? (
                  q.flags.map((f) => (
                    <Tag key={f} componentId="gsb.optimize.flag" color={FLAG[f].color}>
                      {FLAG[f].label}
                    </Tag>
                  ))
                ) : (
                  <Typography.Text color="secondary">None</Typography.Text>
                )}
              </div>
              {q.attempts.some((a) => a.error) && (
                <FormUI.Message type="error" message={q.attempts.find((a) => a.error)?.error ?? ''} />
              )}
            </TableCell>
          </TableRow>
        ))}
      </Table>
    </div>
  );
}

/** Stress test the validated design in the sandbox, with the user's approval and hard limits. */
export function OptimizePage() {
  const { projectId = '', parentId = '' } = useParams();
  const navigate = useNavigate();
  const view = useResource<OptimizeView>(`/api/projects/${projectId}/optimize`);
  const [workload, setWorkload] = useState<WorkloadQuery[]>();
  const [excluded, setExcluded] = useState<WorkloadQuery[]>([]);
  const [repeats, setRepeats] = useState('3');
  const [target, setTarget] = useState('5');
  const [approve, setApprove] = useState(false);
  const [busy, setBusy] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [error, setError] = useState<string>();
  const [tab, setTab] = useState('stress');
  const data = view.data;
  const blocking = data?.practices.filter((c) => c.severity === 'fix' && c.fields.length).length ?? 0;
  const latest = data?.latest;
  const active = latest?.status === 'running' || latest?.status === 'stopping';
  const tryActive = ['running', 'refreshing', 'stopping'].includes(data?.latestTry?.status ?? '');
  const { refresh } = view;

  useEffect(() => {
    if (!active && !tryActive) return;
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [active, tryActive, refresh]);

  const all = workload ?? data?.workload ?? [];
  const chosen = all.filter((q) => !excluded.some((e) => sameQuery(e, q)));
  const runs = Math.min(Math.max(Number(repeats) || 1, 1), data?.limits.maxRepeats ?? 5);
  const targetMs = Math.round(Math.max(Number(target) || 5, 0.1) * 1000);
  const tooMany = chosen.length > (data?.limits.maxQueries ?? 25);

  const start = () => {
    if (!data?.draft || !data.setup) return;
    setBusy(true);
    setError(undefined);
    api(`/api/projects/${projectId}/optimize/runs`, {
      version: data.draft.version,
      queries: chosen,
      settings: { repeats: runs, targetMs },
      statements: data.setup.statements,
    }).then(
      () => {
        setBusy(false);
        setApprove(false);
        refresh();
      },
      (err: unknown) => {
        setBusy(false);
        setApprove(false);
        setError((err as Error).message);
      }
    );
  };

  const stop = (runId = latest?.id) => {
    if (!runId) return;
    setStopping(true);
    api(`/api/projects/${projectId}/optimize/runs/${runId}/stop`, {}).then(refresh, (err: unknown) => {
      setStopping(false);
      setError((err as Error).message);
    });
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <DataState status={view.status} message={view.error} onRetry={view.reload}>
        {data && (!data.draft || data.draft.status !== 'validated') ? (
          <>
            <Alert
              componentId="gsb.optimize.not_validated"
              type="info"
              closable={false}
              message="Validate the design first. The stress test runs on the validated metric view."
              description={
                <Button
                  componentId="gsb.optimize.to_designer"
                  size="small"
                  onClick={() => void navigate(`/projects/${parentId}/sub/${projectId}/designer`)}
                >
                  Open Metric Designer
                </Button>
              }
            />
            {data.draft && <PracticesPanel checks={data.practices} />}
          </>
        ) : data?.draft ? (
          <>
            <Typography.Text color="secondary">
              Run realistic queries on <code>{data.draft.name}</code> version {data.draft.version} in the sandbox, as
              you, on the app&apos;s SQL warehouse. Nothing runs until you approve the plan.
            </Typography.Text>

            <Tabs.Root componentId="gsb.optimize.tabs" value={tab} onValueChange={setTab}>
              <Tabs.List>
                <Tabs.Trigger value="practices">Best practices{blocking ? ` (${blocking} to fix)` : ''}</Tabs.Trigger>
                <Tabs.Trigger value="stress">Stress test</Tabs.Trigger>
                <Tabs.Trigger value="materialize">
                  Materialization{data.suggestion?.views.length ? ` (${data.suggestion.views.length})` : ''}
                </Tabs.Trigger>
                <Tabs.Trigger value="cost">Cost</Tabs.Trigger>
              </Tabs.List>
              <Tabs.Content value="practices">
                <div style={{ paddingTop: 16 }}>
                  <PracticesPanel checks={data.practices} />
                </div>
              </Tabs.Content>
              <Tabs.Content value="materialize">
                <div style={{ paddingTop: 16 }}>
                  <MaterializePanel data={data} projectId={projectId} onChange={refresh} onStop={(id) => stop(id)} />
                </div>
              </Tabs.Content>
              <Tabs.Content value="cost">
                <div style={{ paddingTop: 16 }}>
                  <CostPanel key={`${latest?.id}:${latest?.status}:${data.latestTry?.status}`} projectId={projectId} />
                </div>
              </Tabs.Content>
              <Tabs.Content value="stress">
                <div style={{ display: 'flex', flexDirection: 'column', gap: 16, paddingTop: 16 }}>
                  {latest && <Results run={latest} onStop={() => stop()} stopping={stopping && active} />}

                  <Typography.Title level={4} withoutMargins>
                    Workload ({chosen.length} of {all.length})
                  </Typography.Title>
                  <Typography.Text color="secondary">
                    The validation tests, then each dimension with every measure it can show. Untick the queries you do
                    not need.
                  </Typography.Text>
                  <Table aria-label="Workload">
                    <TableRow isHeader>
                      <TableHeader componentId="gsb.optimize.w_run">Run</TableHeader>
                      <TableHeader componentId="gsb.optimize.w_query">Query</TableHeader>
                      <TableHeader componentId="gsb.optimize.w_dims">Group by</TableHeader>
                      <TableHeader componentId="gsb.optimize.w_from">From</TableHeader>
                    </TableRow>
                    {all.map((q) => (
                      <TableRow key={`${q.origin}:${q.label}`}>
                        <TableCell>
                          <Checkbox
                            componentId="gsb.optimize.include"
                            aria-label={`Run ${q.label}`}
                            isChecked={!excluded.some((e) => sameQuery(e, q))}
                            onChange={(on) =>
                              setExcluded(on ? excluded.filter((e) => !sameQuery(e, q)) : [...excluded, q])
                            }
                          />
                        </TableCell>
                        <TableCell>
                          <div style={WRAP}>
                            <div>{q.label}</div>
                            <Typography.Text color="secondary">{q.measures.join(', ')}</Typography.Text>
                          </div>
                        </TableCell>
                        <TableCell>{q.dimensions.join(', ') || 'Total'}</TableCell>
                        <TableCell>
                          {q.origin === 'test' ? 'Test' : q.origin === 'custom' ? 'You' : 'Generated'}
                        </TableCell>
                      </TableRow>
                    ))}
                  </Table>
                  {data.view && (
                    <AddQuery
                      dimensions={data.view.dimensions}
                      measures={data.view.measures}
                      onAdd={(q) => !all.some((x) => sameQuery(x, q)) && setWorkload([...all, q])}
                    />
                  )}

                  <div style={{ display: 'flex', gap: 16, alignItems: 'flex-end', flexWrap: 'wrap' }}>
                    <div>
                      <FormUI.Label htmlFor="gsb-optimize-repeats">Runs per query</FormUI.Label>
                      <Input
                        componentId="gsb.optimize.repeats"
                        id="gsb-optimize-repeats"
                        type="number"
                        min={1}
                        max={data.limits.maxRepeats}
                        value={repeats}
                        onChange={(e) => setRepeats(e.target.value)}
                        style={{ width: 120 }}
                      />
                    </div>
                    <div>
                      <FormUI.Label htmlFor="gsb-optimize-target">Target (seconds)</FormUI.Label>
                      <Input
                        componentId="gsb.optimize.target"
                        id="gsb-optimize-target"
                        type="number"
                        min={0.5}
                        step={0.5}
                        value={target}
                        onChange={(e) => setTarget(e.target.value)}
                        style={{ width: 120 }}
                      />
                    </div>
                    <Button
                      componentId="gsb.optimize.review"
                      type="primary"
                      disabled={!chosen.length || tooMany || active || tryActive || !data.setup}
                      onClick={() => setApprove(true)}
                    >
                      Review and run
                    </Button>
                    <Typography.Text color="secondary">
                      {chosen.length} queries x {runs} runs = {chosen.length * runs} statements. Each stops after{' '}
                      {data.limits.timeoutSeconds} s.
                    </Typography.Text>
                  </div>
                  {tooMany && (
                    <FormUI.Message type="error" message={`Run at most ${data.limits.maxQueries} queries at a time.`} />
                  )}
                  {!data.setup && (
                    <FormUI.Message type="error" message="The sandbox schema is not configured. Ask the app admin." />
                  )}
                  {error && <Alert componentId="gsb.optimize.error" type="error" closable={false} message={error} />}

                  {approve && data.setup && (
                    <Modal
                      componentId="gsb.optimize.approve"
                      title="Run the stress test"
                      visible
                      okText="Run"
                      cancelText="Cancel"
                      confirmLoading={busy}
                      onOk={start}
                      onCancel={() => setApprove(false)}
                      size="wide"
                    >
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                        <Typography.Text>
                          The app creates the sandbox view, then runs {chosen.length} queries {runs} times each, one at
                          a time, as you on the app&apos;s SQL warehouse. It reads only aggregates, at most 1,000 rows
                          per query. You can stop it at any time.
                        </Typography.Text>
                        <SqlBlock label="SQL to run first" sql={data.setup.statements.join('\n\n')} />
                      </div>
                    </Modal>
                  )}
                </div>
              </Tabs.Content>
            </Tabs.Root>
          </>
        ) : null}
      </DataState>
    </div>
  );
}
