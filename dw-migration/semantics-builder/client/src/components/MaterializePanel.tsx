import { useState } from 'react';
import {
  Alert,
  Button,
  Checkbox,
  Modal,
  SimpleSelect,
  SimpleSelectOption,
  Table,
  TableCell,
  TableHeader,
  TableRow,
  Tag,
  Typography,
} from '@databricks/design-system';
import { SCHEDULES } from '../../../shared/optimize';
import type { OptimizeView, Schedule, StressRun, TryPlan } from '../../../shared/optimize';
import { api } from '../api';
import { SqlBlock } from './SqlBlock';

const WRAP = { whiteSpace: 'normal', overflowWrap: 'anywhere' } as const;
const secs = (v: number | null | undefined) => (v === null || v === undefined ? '-' : `${(v / 1000).toFixed(1)} s`);

function Approve({
  title,
  intro,
  statements,
  okText,
  onOk,
  onCancel,
}: {
  title: string;
  intro: string;
  statements: string[];
  okText: string;
  onOk: () => Promise<void>;
  onCancel: () => void;
}) {
  const [busy, setBusy] = useState(false);
  return (
    <Modal
      componentId="gsb.materialize.approve"
      title={title}
      visible
      okText={okText}
      cancelText="Cancel"
      confirmLoading={busy}
      onOk={() => {
        setBusy(true);
        void onOk().finally(() => setBusy(false));
      }}
      onCancel={onCancel}
      size="wide"
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <Typography.Text>{intro}</Typography.Text>
        {statements.map((s) => (
          <SqlBlock key={s} label="SQL to run" sql={s} />
        ))}
      </div>
    </Modal>
  );
}

/** Before and after per query, with the materialization each query read. */
function TryResults({
  run,
  base,
  projectId,
  onChange,
  onStop,
}: {
  run: StressRun;
  base: StressRun | null;
  projectId: string;
  onChange: () => void;
  onStop: () => void;
}) {
  const [removal, setRemoval] = useState<string[]>();
  const [error, setError] = useState<string>();
  const mat = run.materialization!;
  const active = ['running', 'refreshing', 'stopping'].includes(run.status);
  const before = base?.id === mat.baseRun ? base : null;
  const matched = run.queries.filter((q) => q.matched).length;

  const askRemove = () =>
    api<{ statements: string[] }>(`/api/projects/${projectId}/optimize/tries/${run.id}/remove`).then(
      (r) => setRemoval(r.statements),
      (err: unknown) => setError((err as Error).message)
    );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <Typography.Title level={4} withoutMargins>
          Last materialization try
        </Typography.Title>
        <Tag
          componentId="gsb.materialize.status"
          color={run.status === 'failed' ? 'coral' : active ? 'indigo' : 'teal'}
        >
          {run.status === 'refreshing'
            ? 'Waiting for the first refresh'
            : run.status[0].toUpperCase() + run.status.slice(1)}
        </Tag>
        {mat.removed && <Tag componentId="gsb.materialize.removed">Removed</Tag>}
        <Typography.Text color="secondary">
          {mat.views.map((v) => v.name).join(', ')}, {mat.schedule}
          {mat.refreshMs !== undefined ? `, first refresh ${secs(mat.refreshMs)}` : ''}
        </Typography.Text>
        {mat.pipelineUrl && (
          <Typography.Link componentId="gsb.materialize.pipeline" href={mat.pipelineUrl} openInNewTab>
            Pipeline
          </Typography.Link>
        )}
        {active ? (
          <Button componentId="gsb.materialize.stop" size="small" danger onClick={onStop}>
            Stop
          </Button>
        ) : (
          !mat.removed && (
            <Button componentId="gsb.materialize.remove" size="small" onClick={() => void askRemove()}>
              Remove the sandbox materialization
            </Button>
          )
        )}
      </div>
      {run.error && <Alert componentId="gsb.materialize.error" type="error" closable={false} message={run.error} />}
      {error && <Alert componentId="gsb.materialize.action_error" type="error" closable={false} message={error} />}
      {mat.removed && mat.pipelineUrl && (
        <Alert
          componentId="gsb.materialize.pipeline_left"
          type="info"
          closable={false}
          message="The materialization is off and the sandbox view is dropped. The empty pipeline stays: the app cannot delete pipelines. Delete it from the Pipeline link if you want."
        />
      )}
      {run.status === 'finished' && (
        <Alert
          componentId="gsb.materialize.summary"
          type={matched ? 'success' : 'warning'}
          closable={false}
          message={`${matched} of ${run.queries.length} queries read a materialization.`}
          description="Matched queries return data from the last refresh. The others read the sources, as before."
        />
      )}
      <Table aria-label="Before and after" scrollable>
        <TableRow isHeader>
          <TableHeader componentId="gsb.materialize.c_query">Query</TableHeader>
          <TableHeader componentId="gsb.materialize.c_before">Before</TableHeader>
          <TableHeader componentId="gsb.materialize.c_after">After</TableHeader>
          <TableHeader componentId="gsb.materialize.c_change">Change</TableHeader>
          <TableHeader componentId="gsb.materialize.c_reads">Reads</TableHeader>
        </TableRow>
        {run.queries.map((q) => {
          const b = before?.queries.find((x) => x.label === q.label)?.warmMs ?? null;
          const change = b !== null && q.warmMs !== null && b > 0 ? Math.round(((q.warmMs - b) / b) * 100) : null;
          return (
            <TableRow key={`${q.origin}:${q.label}`}>
              <TableCell>
                <div style={WRAP}>{q.label}</div>
              </TableCell>
              <TableCell>{secs(b)}</TableCell>
              <TableCell>{active && q.warmMs === null ? 'Waiting' : secs(q.warmMs)}</TableCell>
              <TableCell>{change === null ? '-' : `${change > 0 ? '+' : ''}${change}%`}</TableCell>
              <TableCell>
                {q.matched === undefined || (active && q.matched === null) ? (
                  '-'
                ) : q.matched ? (
                  <Tag componentId="gsb.materialize.matched" color="teal">
                    {q.matched}
                  </Tag>
                ) : (
                  'Sources'
                )}
              </TableCell>
            </TableRow>
          );
        })}
      </Table>
      {removal && (
        <Approve
          title="Remove the sandbox materialization"
          intro="The first statement turns the materialization off, so it stops refreshing. The second drops the sandbox view."
          statements={removal}
          okText="Remove"
          onCancel={() => setRemoval(undefined)}
          onOk={() =>
            api(`/api/projects/${projectId}/optimize/tries/${run.id}/remove`, { statements: removal }).then(
              () => {
                setRemoval(undefined);
                onChange();
              },
              (err: unknown) => {
                setRemoval(undefined);
                setError((err as Error).message);
              }
            )
          }
        />
      )}
    </div>
  );
}

/** Rule-based suggestions from the last stress test, and a try in the sandbox. */
export function MaterializePanel({
  data,
  projectId,
  onChange,
  onStop,
}: {
  data: OptimizeView;
  projectId: string;
  onChange: () => void;
  onStop: (runId: string) => void;
}) {
  const s = data.suggestion;
  const [off, setOff] = useState<string[]>([]);
  const [schedule, setSchedule] = useState<Schedule>('every 24 hours');
  const [plan, setPlan] = useState<TryPlan>();
  const [error, setError] = useState<string>();
  const busy = [data.latest, data.latestTry].some((r) => r && ['running', 'refreshing', 'stopping'].includes(r.status));
  const chosen = s?.views.filter((v) => !off.includes(v.name)) ?? [];

  const askPlan = () =>
    api<TryPlan>(
      `/api/projects/${projectId}/optimize/tries/plan?schedule=${encodeURIComponent(schedule)}&views=${encodeURIComponent(chosen.map((v) => v.name).join(','))}`
    ).then(setPlan, (err: unknown) => setError((err as Error).message));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Typography.Title level={4} withoutMargins>
        Materialization suggestions
      </Typography.Title>
      {!s ? (
        <Typography.Text color="secondary">
          Run a stress test of version {data.draft?.version} to get suggestions.
        </Typography.Text>
      ) : !s.views.length ? (
        <Alert
          componentId="gsb.materialize.none"
          type="success"
          closable={false}
          message="No materialization needed. Every measured query already runs in under 1 s."
        />
      ) : (
        <>
          <Typography.Text color="secondary">
            One aggregated materialization per group of slow queries, slowest first. Queries with only additive measures
            roll up from a wider one.
          </Typography.Text>
          <Table aria-label="Suggested materializations">
            <TableRow isHeader>
              <TableHeader componentId="gsb.materialize.s_use">Use</TableHeader>
              <TableHeader componentId="gsb.materialize.s_name">Materialization</TableHeader>
              <TableHeader componentId="gsb.materialize.s_dims">Dimensions</TableHeader>
              <TableHeader componentId="gsb.materialize.s_why">Why</TableHeader>
            </TableRow>
            {s.views.map((v) => (
              <TableRow key={v.name}>
                <TableCell>
                  <Checkbox
                    componentId="gsb.materialize.use"
                    aria-label={`Use ${v.name}`}
                    isChecked={!off.includes(v.name)}
                    onChange={(on) => setOff(on ? off.filter((x) => x !== v.name) : [...off, v.name])}
                  />
                </TableCell>
                <TableCell>
                  <div style={WRAP}>
                    <code>{v.name}</code>
                    <div>
                      <Typography.Text color="secondary">{v.measures.join(', ')}</Typography.Text>
                    </div>
                  </div>
                </TableCell>
                <TableCell>
                  <div style={WRAP}>{v.dimensions.join(', ') || 'Total'}</div>
                </TableCell>
                <TableCell>
                  <div style={WRAP}>
                    {v.reason} Serves: {v.queries.join('; ')}.
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </Table>
          {s.skipped.length > 0 && (
            <Typography.Text color="secondary">
              Not materialized: {s.skipped.map((x) => `${x.label} (${x.reason.replace(/\.$/, '')})`).join('; ')}.
            </Typography.Text>
          )}
          <ul style={{ margin: 0, paddingLeft: 20 }}>
            {s.notes.map((n) => (
              <li key={n}>
                <Typography.Text color="secondary">{n}</Typography.Text>
              </li>
            ))}
          </ul>
          <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <SimpleSelect
              componentId="gsb.materialize.schedule"
              id="gsb-materialize-schedule"
              label="Refresh"
              value={schedule}
              onChange={(e) => setSchedule(e.target.value as Schedule)}
            >
              {SCHEDULES.map((x) => (
                <SimpleSelectOption key={x} value={x}>
                  {x[0].toUpperCase() + x.slice(1)}
                </SimpleSelectOption>
              ))}
            </SimpleSelect>
            <Button
              componentId="gsb.materialize.try"
              type="primary"
              disabled={!chosen.length || busy}
              onClick={() => void askPlan()}
            >
              Try in sandbox
            </Button>
            <Typography.Text color="secondary">
              Creates a materialized copy in the sandbox, waits for the first refresh, then runs the same workload.
            </Typography.Text>
          </div>
        </>
      )}
      {error && <Alert componentId="gsb.materialize.plan_error" type="error" closable={false} message={error} />}
      {data.latestTry && (
        <TryResults
          run={data.latestTry}
          base={data.latest}
          projectId={projectId}
          onChange={onChange}
          onStop={() => onStop(data.latestTry!.id)}
        />
      )}
      {plan && data.draft && (
        <Approve
          title="Try the materialization in the sandbox"
          intro={`This creates ${plan.matView} with ${chosen.length} materialization${chosen.length === 1 ? '' : 's'}. A Lakeflow pipeline refreshes it ${schedule}, billed as pipeline DBUs, until you remove it. Then the same ${data.latest?.queries.length ?? 0} queries run again.`}
          statements={plan.statements}
          okText="Create and test"
          onCancel={() => setPlan(undefined)}
          onOk={() =>
            api(`/api/projects/${projectId}/optimize/tries`, {
              version: data.draft!.version,
              schedule,
              views: chosen.map((v) => v.name),
              statements: plan.statements,
            }).then(
              () => {
                setPlan(undefined);
                onChange();
              },
              (err: unknown) => {
                setPlan(undefined);
                setError((err as Error).message);
              }
            )
          }
        />
      )}
    </div>
  );
}
