import { useState } from 'react';
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
import type { BilledDbus, CostRun, CostView, Schedule } from '../../../shared/optimize';
import { api, useResource } from '../api';
import { DataState } from './DataState';

const secs = (ms: number | null | undefined) =>
  ms == null ? '-' : ms < 60_000 ? `${(ms / 1000).toFixed(1)} s` : `${(ms / 60_000).toFixed(1)} min`;
const mb = (b: number) => (b ? `${(b / 1024 ** 2).toFixed(1)} MB` : '-');
const REFRESHES_PER_DAY: Record<Schedule, number> = { 'every 1 hour': 24, 'every 6 hours': 4, 'every 24 hours': 1 };

function csv(runs: CostRun[], dbus: Map<string, number>) {
  const head = [
    'run',
    'kind',
    'version',
    'status',
    'created_by',
    'created_at',
    'statements',
    'exec_ms',
    'task_ms',
    'read_bytes',
    'cached_runs',
    'pipeline_id',
    'refresh_ms',
    'pipeline_dbus',
    'saved_ms_per_run',
  ];
  const cell = (v: string | number | null | undefined) => (v == null ? '' : `"${String(v).replace(/"/g, '""')}"`);
  const rows = runs.map((r) =>
    [
      r.id,
      r.kind,
      r.version,
      r.status,
      r.createdBy,
      r.createdAt,
      r.statements,
      r.execMs,
      r.taskMs,
      r.readBytes,
      r.cachedRuns,
      r.pipelineId,
      r.refreshMs,
      r.pipelineId ? dbus.get(r.pipelineId) : null,
      r.savedMsPerRun,
    ]
      .map(cell)
      .join(',')
  );
  const url = URL.createObjectURL(new Blob([[head.join(','), ...rows].join('\n')], { type: 'text/csv' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = 'semantics-builder-cost.csv';
  a.click();
  URL.revokeObjectURL(url);
}

/** What the app ran for this sub-project, the monthly budget, and the trade-off of each materialization try. */
export function CostPanel({ projectId }: { projectId: string }) {
  const cost = useResource<CostView>(`/api/projects/${projectId}/optimize/cost`);
  const [minutes, setMinutes] = useState<string>();
  const [rate, setRate] = useState('');
  const [perDay, setPerDay] = useState('100');
  const [billed, setBilled] = useState<BilledDbus>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>();
  const data = cost.data;
  const dbus = new Map((billed?.pipelines ?? []).map((p) => [p.pipelineId, p.dbus]));
  const tries = data?.runs.filter((r) => r.kind === 'try') ?? [];
  const usedPct = data?.budgetMs ? Math.min(100, Math.round((data.usedMs / data.budgetMs) * 100)) : null;

  const saveBudget = () => {
    const m = minutes?.trim() ? Number(minutes) : null;
    api<CostView>(`/api/projects/${projectId}/optimize/budget`, { minutes: m }).then(
      (v) => {
        cost.setData(v);
        setMinutes(undefined);
      },
      (err: unknown) => setError((err as Error).message)
    );
  };
  const loadDbus = () => {
    setLoading(true);
    api<BilledDbus>(`/api/projects/${projectId}/optimize/cost/dbus`, {}).then(
      (b) => {
        setLoading(false);
        setBilled(b);
      },
      (err: unknown) => {
        setLoading(false);
        setError((err as Error).message);
      }
    );
  };

  return (
    <DataState status={cost.status} message={cost.error} onRetry={cost.reload}>
      {data && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Typography.Text color="secondary">
            Warehouse time the app used for stress tests and materialization tries, as execution time from the Query
            History. Times and DBUs, not money: list prices differ by cloud, region and contract.
          </Typography.Text>

          <div style={{ display: 'flex', gap: 16, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <div>
              <Typography.Text bold>This month</Typography.Text>
              <div>
                <Typography.Text>
                  {secs(data.usedMs)}
                  {data.budgetMs ? ` of ${secs(data.budgetMs)} (${usedPct}%)` : ', no budget set'}
                </Typography.Text>
              </div>
            </div>
            {data.canEdit && (
              <>
                <div>
                  <FormUI.Label htmlFor="gsb-cost-budget">Monthly budget (minutes)</FormUI.Label>
                  <Input
                    componentId="gsb.cost.budget"
                    id="gsb-cost-budget"
                    type="number"
                    min={1}
                    placeholder="No budget"
                    value={minutes ?? (data.budgetMs ? String(data.budgetMs / 60_000) : '')}
                    onChange={(e) => setMinutes(e.target.value)}
                    style={{ width: 160 }}
                  />
                </div>
                <Button componentId="gsb.cost.save_budget" disabled={minutes === undefined} onClick={saveBudget}>
                  Save budget
                </Button>
              </>
            )}
            <Button componentId="gsb.cost.export" disabled={!data.runs.length} onClick={() => csv(data.runs, dbus)}>
              Export CSV
            </Button>
          </div>
          {usedPct !== null && usedPct >= 80 && (
            <Alert
              componentId="gsb.cost.budget_warning"
              type="warning"
              closable={false}
              message={`${usedPct}% of the monthly budget is used. Runs stop when it is spent.`}
            />
          )}
          {error && <Alert componentId="gsb.cost.error" type="error" closable={false} message={error} />}

          <Table aria-label="Runs and their cost" scrollable>
            <TableRow isHeader>
              <TableHeader componentId="gsb.cost.c_when">When</TableHeader>
              <TableHeader componentId="gsb.cost.c_kind">Run</TableHeader>
              <TableHeader componentId="gsb.cost.c_statements">Statements</TableHeader>
              <TableHeader componentId="gsb.cost.c_exec">Execution</TableHeader>
              <TableHeader componentId="gsb.cost.c_task">Task time</TableHeader>
              <TableHeader componentId="gsb.cost.c_read">Read</TableHeader>
              <TableHeader componentId="gsb.cost.c_by">By</TableHeader>
            </TableRow>
            {data.runs.map((r) => (
              <TableRow key={r.id}>
                <TableCell>{new Date(r.createdAt).toLocaleString()}</TableCell>
                <TableCell>
                  <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    <Tag componentId="gsb.cost.kind" color={r.kind === 'try' ? 'indigo' : 'default'}>
                      {r.kind === 'try' ? 'Materialization try' : 'Stress test'}
                    </Tag>
                    <Typography.Text color="secondary">
                      v{r.version}, {r.status}
                    </Typography.Text>
                  </div>
                </TableCell>
                <TableCell>
                  {r.statements}
                  {r.cachedRuns ? ` (${r.cachedRuns} cached)` : ''}
                </TableCell>
                <TableCell>{secs(r.execMs)}</TableCell>
                <TableCell>{secs(r.taskMs)}</TableCell>
                <TableCell>{mb(r.readBytes)}</TableCell>
                <TableCell>{r.createdBy}</TableCell>
              </TableRow>
            ))}
          </Table>
          {!data.runs.length && <Typography.Text color="secondary">No runs yet.</Typography.Text>}

          {tries.length > 0 && (
            <>
              <Typography.Title level={4} withoutMargins>
                Materialization trade-off
              </Typography.Title>
              <Typography.Text color="secondary">
                A materialization costs pipeline DBUs on each refresh and saves warehouse time on each matched query.
                Enter how often the matched queries run to compare the two.
              </Typography.Text>
              <div style={{ display: 'flex', gap: 16, alignItems: 'flex-end', flexWrap: 'wrap' }}>
                <div>
                  <FormUI.Label htmlFor="gsb-cost-perday">Matched queries per day</FormUI.Label>
                  <Input
                    componentId="gsb.cost.per_day"
                    id="gsb-cost-perday"
                    type="number"
                    min={0}
                    value={perDay}
                    onChange={(e) => setPerDay(e.target.value)}
                    style={{ width: 160 }}
                  />
                </div>
                <div>
                  <FormUI.Label htmlFor="gsb-cost-rate">Your price per DBU (optional)</FormUI.Label>
                  <Input
                    componentId="gsb.cost.rate"
                    id="gsb-cost-rate"
                    type="number"
                    min={0}
                    step={0.01}
                    placeholder="For example 0.70"
                    value={rate}
                    onChange={(e) => setRate(e.target.value)}
                    style={{ width: 160 }}
                  />
                </div>
                <Button componentId="gsb.cost.dbus" loading={loading} onClick={loadDbus}>
                  Load billed DBUs
                </Button>
              </div>
              {billed?.error && (
                <Alert componentId="gsb.cost.dbus_error" type="info" closable={false} message={billed.error} />
              )}
              {billed && !billed.error && !billed.pipelines.length && (
                <Typography.Text color="secondary">
                  No billing rows yet. Billing data arrives a few hours after a refresh.
                </Typography.Text>
              )}
              <Table aria-label="Materialization trade-off" scrollable>
                <TableRow isHeader>
                  <TableHeader componentId="gsb.cost.t_views">Materializations</TableHeader>
                  <TableHeader componentId="gsb.cost.t_refresh">First refresh</TableHeader>
                  <TableHeader componentId="gsb.cost.t_dbus">Billed DBUs</TableHeader>
                  <TableHeader componentId="gsb.cost.t_refresh_day">DBUs per day</TableHeader>
                  <TableHeader componentId="gsb.cost.t_saved">Query time saved per day</TableHeader>
                </TableRow>
                {tries.map((t) => {
                  const billedDbus = t.pipelineId ? dbus.get(t.pipelineId) : undefined;
                  const perRefresh = billedDbus;
                  const day =
                    perRefresh !== undefined && t.schedule ? perRefresh * REFRESHES_PER_DAY[t.schedule] : undefined;
                  const saved =
                    t.savedMsPerRun !== undefined && t.matched
                      ? (t.savedMsPerRun / t.matched) * (Number(perDay) || 0)
                      : undefined;
                  const money =
                    day !== undefined && Number(rate) > 0 ? ` (about ${(day * Number(rate)).toFixed(2)} per day)` : '';
                  return (
                    <TableRow key={t.id}>
                      <TableCell>
                        <div style={{ whiteSpace: 'normal' }}>
                          {(t.views ?? []).join(', ')}
                          <div>
                            <Typography.Text color="secondary">
                              {t.schedule}, {t.matched ?? 0} matched queries,{' '}
                              {new Date(t.createdAt).toLocaleDateString()}
                            </Typography.Text>
                          </div>
                        </div>
                      </TableCell>
                      <TableCell>{secs(t.refreshMs)}</TableCell>
                      <TableCell>{billedDbus === undefined ? '-' : billedDbus.toFixed(2)}</TableCell>
                      <TableCell>{day === undefined ? '-' : `${day.toFixed(2)}${money}`}</TableCell>
                      <TableCell>{saved === undefined ? '-' : secs(saved)}</TableCell>
                    </TableRow>
                  );
                })}
              </Table>
              <Typography.Text color="secondary">
                DBUs per day assume the billed DBUs cover the first refresh only, which holds when the try was removed
                before its next scheduled refresh. Saved time is warm execution time on the warehouse; its DBUs depend
                on the warehouse size.
              </Typography.Text>
            </>
          )}
        </div>
      )}
    </DataState>
  );
}
