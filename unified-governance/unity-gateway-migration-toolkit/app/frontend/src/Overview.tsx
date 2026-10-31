import { useEffect, useId, useState } from "react";
import { api, fmt, jobRunning, pct, useApi, useJob } from "./api";
import { Badge, Bars, Card, Empty, ErrorBox, ErrorState, ExportMenu, JobLine, Kpi, PageHeader, SkeletonCard, SkeletonKpis, Table, TrendChart } from "./ui";
import type { Column } from "./ui";

type Workspace = {
  workspace_id: string; workspace_name: string | null; status: string | null; wave: string; readiness: string | null; ready: boolean;
  scan_readiness: string | null; legacy_endpoints: number | null; custom_legacy_endpoints: number | null;
  active_legacy_endpoints: number | null; unknown_traffic_endpoints: number | null; v1_requests: number | null;
  v2_requests: number | null; legacy_requests: number | null; legacy_throttled: number | null;
  deleted_endpoint_requests: number | null; v3_requests: number | null; v3_share: number | null; last_seen: string | null;
  config_signals: string[]; due_for: "v1" | "v2" | null; due_date: string | null; due_days_left: number | null;
};
type Endpoint = {
  workspace_name: string | null; endpoint_name: string; kind: string; live: boolean; requests: number; requesters: number;
  throttled: number; last_seen: string | null; traffic_status: string | null;
};
type Overview = {
  snapshot_time: string | null; window_days: number | null; window_assumed: boolean; run_id: string | null;
  running_snapshot: { job_run_id: string; started_at: string | null } | null;
  trend: Record<string, any>[];
  kpis: Record<string, number | null>;
  deadlines: { v2: { date: string; days_left: number; what: string }; v1: { date: string; days_left: number; what: string }; note: string };
  waves: { wave: string; workspaces: number }[];
  workspaces: Workspace[];
  endpoints: Endpoint[];
  endpoints_limit: number;
  endpoints_total: number;
};

/** Tone per wave: wave 0 is good only as a candidate; unknown traffic and missing data stay visible as warnings. */
const WAVE_TONE = (w: string) =>
  w === "0: traffic unknown" ? "warn" : w.startsWith("0") ? "good" : w.startsWith("v2") || w.startsWith("2") ? "bad" : w === "not running" ? "neutral" : "warn";

const WAVE_HELP: Record<string, string> = {
  "v2 first": "Calls to AI Gateway v2 endpoints. Move these first: v2 endpoints stop serving on November 30, 2026.",
  "2: high volume": "Legacy (v1) traffic of 10,000 requests or more in the window.",
  "1: small": "Some legacy (v1) traffic, under 10,000 requests in the window.",
  "1: cleanup": "No legacy traffic, but external model, Provisioned Throughput (PT) or other endpoints block wave 0. Retire or apply them first.",
  "0: traffic unknown": "Live legacy endpoints with no usage rows in the last 365 days. Usage tracking may be off, so traffic can't be confirmed until a workspace scan.",
  "0: no legacy traffic": "No legacy (v1) requests in the window. This is not ready: a passing workspace scan is required.",
  "no endpoint data": "Nothing for this workspace in the account tables (no endpoints, legacy requests or AI Gateway rows). A workspace scan confirms it.",
  "not running": "The workspace isn't running, so it isn't counted.",
  unknown: "A query failed while this snapshot was taken, so the wave is unknown. Refresh the snapshot.",
};

const SIGNAL_LABEL: Record<string, string> = {
  VECTOR_SEARCH: "AI Search", AGENT_BRICKS: "Agent Bricks", SUPERVISOR_AGENT: "Agent Bricks supervisor",
  APPS: "Apps", AI_FUNCTIONS: "AI Functions",
};

/** Date in UTC, e.g. "Oct 28, 2026 06:00 UTC". */
function utc(iso: string | null | undefined) {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }) + " UTC";
}

/** "3 days ago", "5 hours ago", "just now". */
function ago(iso: string | null | undefined) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (Number.isNaN(s)) return "";
  if (s < 90) return "just now";
  const m = s / 60;
  if (m < 60) return `${Math.round(m)} minutes ago`;
  const h = m / 60;
  if (h < 48) return `${Math.round(h)} hours ago`;
  return `${Math.round(h / 24)} days ago`;
}

const dateOnly = (iso: string | null | undefined) => (iso ? String(iso).slice(0, 10) : "-");

function daysLabel(n: number | null | undefined) {
  if (n === null || n === undefined) return "";
  if (n < 0) return "passed";
  return n === 0 ? "today" : `${n} days left`;
}

/** Table under a chart, hidden until asked for, so the chart's numbers can be read or copied. */
function ViewData<T extends Record<string, any>>({ rows, columns, label }: { rows: T[]; columns: Column<T>[]; label: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className="stack-sm">
      <div>
        <button className="btn secondary sm" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
          {open ? "Hide data" : "View data"}
        </button>
      </div>
      <div id={id} hidden={!open}>
        {open && <Table label={label} rows={rows} columns={columns} />}
      </div>
    </div>
  );
}

export default function Overview({ operator }: { operator: boolean }) {
  const { data, error, loading, reload } = useApi<Overview>("/api/overview");
  const [jobId, setJobId] = useState<string | null>(null);
  const [startErr, setStartErr] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const job = useJob(jobId, () => reload());

  // A snapshot that was started by someone else (or by the weekly schedule) is shown and polled too.
  const runningId = data?.running_snapshot?.job_run_id ?? null;
  useEffect(() => {
    if (runningId && runningId !== jobId) setJobId(runningId);
  }, [runningId]);

  const refresh = async () => {
    setStartErr(null);
    setStarting(true);
    try {
      const r = await api("/api/account/snapshot", { method: "POST" });
      setJobId(r.job_run_id);
    } catch (e: any) {
      setStartErr(e.message);
    } finally {
      setStarting(false);
    }
  };

  const running = jobRunning(jobId, job);
  const disabledReason = !operator
    ? "Only operators can start a refresh."
    : running
      ? "A snapshot is already running."
      : starting
        ? "Starting the snapshot."
        : null;
  const refreshButton = (
    <div className="row">
      <button className="btn" onClick={refresh} disabled={!!disabledReason}>
        {starting || running ? "Refreshing…" : "Refresh snapshot"}
      </button>
      {disabledReason && <span className="small muted">{disabledReason}</span>}
    </div>
  );
  const hasData = !!data?.trend?.length;
  const exports = hasData && (
    <ExportMenu items={[
      { href: "/api/export/overview/workspaces", label: "Workspaces", hint: "CSV" },
      { href: "/api/export/overview/endpoints", label: "All legacy endpoints", hint: "CSV" },
      { href: "/api/export/overview/trend", label: "Trend across snapshots", hint: "CSV" },
    ]} />
  );
  const latest = data?.trend?.[data.trend.length - 1];
  const windowDays = data?.window_days ?? 30;
  const windowLabel = `${windowDays}-day window${data?.window_assumed ? " (assumed: this snapshot predates window tracking)" : ""}`;
  const k = data?.kpis ?? {};
  const runningCount = k.running_workspaces ?? 0;

  return (
    <div className="stack">
      <PageHeader title="Account overview"
                  description={latest && data ? (
                    <>
                      Snapshot taken {ago(data.snapshot_time)} ({utc(data.snapshot_time)}) · rolling {windowLabel} · legacy = v1 + v2
                      {data.running_snapshot?.started_at && running && <> · running since {utc(data.running_snapshot.started_at)}</>}
                    </>
                  ) : undefined}
                  actions={<>{exports}{refreshButton}</>} />
      {jobId && <JobLine state={job} label="Snapshot" done="The overview now shows the new snapshot." />}
      {startErr && <ErrorBox error={startErr} />}

      {loading && !data ? (
        <>
          <SkeletonKpis />
          <div className="grid2"><SkeletonCard title="Traffic" block /><SkeletonCard title="Workspaces by wave" block /></div>
          <SkeletonCard title="Workspaces" />
        </>
      ) : error ? (
        <ErrorState error={error} onRetry={reload} title="Couldn't load the account snapshot" />
      ) : !latest ? (
        <Empty title="No snapshot yet"
               action={operator ? refreshButton : <span className="small">Ask an operator to refresh the snapshot.</span>}>
          A snapshot reads this account's system tables (a few minutes, including job start-up).
        </Empty>
      ) : (
        <>
          <div className="kpis">
            <Kpi label={`No legacy traffic in ${windowDays} days`} value={`${fmt(k.no_traffic)} of ${fmt(runningCount)}`}
                 sub="running workspaces. Not ready yet: each needs a passing scan" />
            <Kpi label="Ready to enforce" value={`${fmt(k.ready)} of ${fmt(runningCount)}`}
                 sub="running workspaces with a passing scan in the window" tone={k.ready ? "good" : undefined} />
            <Kpi label="Legacy requests" value={fmt(k.legacy_requests)}
                 sub={`v1 + v2, ${windowDays} days; ${fmt(k.active_legacy_endpoints)} active endpoints`}
                 tone={Number(k.legacy_requests) ? "bad" : "good"} />
            <Kpi label="Share on Unity Gateway" value={pct(k.v3_share)} sub={`${fmt(k.v3_requests)} requests`} />
            <Kpi label="Days to v2 stop" value={daysLabel(data!.deadlines.v2.days_left)}
                  sub={`${data!.deadlines.v2.date}; confirm with your account team`} tone={data!.deadlines.v2.days_left < 30 ? "bad" : "warn"} />
            <Kpi label="Days to v1 retirement" value={daysLabel(data!.deadlines.v1.days_left)}
                  sub={`${data!.deadlines.v1.date}; confirm with your account team`} />
          </div>
          {k.no_endpoint_data ? (
            <p className="small muted">
              {fmt(k.no_endpoint_data)} running workspaces have no endpoint data in the account tables. They count as running but aren't
              wave 0 until a scan says so. Denominator: {fmt(runningCount)} running workspaces.
            </p>
          ) : null}

          <div className="grid2">
            <Card title="Legacy vs Unity Gateway requests" note={`One point per snapshot; each is a rolling ${windowDays}-day window, so consecutive points overlap.`}>
              <TrendChart label="Legacy vs Unity Gateway requests" points={data!.trend}
                          series={[{ key: "legacy_requests", label: "Legacy (v1 + v2)", cls: "legacy" }, { key: "v3_requests", label: "Unity Gateway", cls: "ug" }]} />
              <ViewData label="Legacy vs Unity Gateway requests, by snapshot" rows={data!.trend} columns={[
                { key: "snapshot_time", label: "Snapshot", render: (r) => dateOnly(r.snapshot_time) },
                { key: "legacy_requests", label: "Legacy (v1 + v2)", num: true, render: (r) => fmt(r.legacy_requests) },
                { key: "v3_requests", label: "Unity Gateway", num: true, render: (r) => fmt(r.v3_requests) },
              ]} />
            </Card>
            <Card title="Workspaces with no legacy traffic" note="Wave 0 per snapshot. Not the same as ready: a passing scan is also needed.">
              <TrendChart label="Workspaces with no legacy traffic" points={data!.trend} series={[{ key: "no_traffic", label: "No legacy traffic", cls: "single" }]} />
              <ViewData label="Workspaces with no legacy traffic, by snapshot" rows={data!.trend} columns={[
                { key: "snapshot_time", label: "Snapshot", render: (r) => dateOnly(r.snapshot_time) },
                { key: "no_traffic", label: "No legacy traffic", num: true, render: (r) => fmt(r.no_traffic) },
                { key: "workspaces", label: "Running workspaces", num: true, render: (r) => fmt(r.workspaces) },
              ]} />
            </Card>
          </div>

          <Card title="Workspaces by migration wave"
                note="Waves are ordered by what to do first. Each workspace is in one wave; wave 0 needs a passing scan before it counts as ready.">
            <Bars label="Workspaces by migration wave" rows={data!.waves} labelKey="wave" valueKey="workspaces" />
            <ul className="small stack-sm" style={{ paddingLeft: "1.2em" }}>
              {data!.waves.map((w) => (
                <li key={w.wave}><Badge value={w.wave} tone={WAVE_TONE(w.wave)} /> {WAVE_HELP[w.wave] || ""}</li>
              ))}
            </ul>
            <ViewData label="Workspaces by migration wave" rows={data!.waves} columns={[
              { key: "wave", label: "Wave" },
              { key: "workspaces", label: "Workspaces", num: true, render: (r) => fmt(r.workspaces) },
            ]} />
          </Card>

          <Card title="Workspaces" note="Busiest first. Due date: v2 when a workspace has v2 traffic, otherwise v1 retirement for legacy endpoints. Scan a workspace for details.">
            <Table search label="Workspaces" rows={data!.workspaces} columns={[
              { key: "workspace_name", label: "Workspace", render: (r) => (
                <>
                  <b>{r.workspace_name || "-"}</b>
                  <div className="muted small">{r.workspace_id}</div>
                  {r.config_signals?.length > 0 && (
                    <div className="small">Check: {r.config_signals.map((s: string) => SIGNAL_LABEL[s] || s).join(", ")}</div>
                  )}
                </>) },
              { key: "wave", label: "Wave", render: (r) => (
                <>
                  <Badge value={r.wave} tone={WAVE_TONE(String(r.wave))} />
                  {r.readiness && <div className={`small ${r.ready ? "" : "muted"}`}>{r.readiness}</div>}
                </>) },
              { key: "legacy_endpoints", label: "Live legacy endpoints", num: true, render: (r) => (
                <>{fmt(r.legacy_endpoints)}{Number(r.custom_legacy_endpoints) > 0 && <div className="small muted">{fmt(r.custom_legacy_endpoints)} external / PT / other</div>}</>) },
              { key: "active_legacy_endpoints", label: "Active", num: true, render: (r) => fmt(r.active_legacy_endpoints) },
              { key: "unknown_traffic_endpoints", label: "Traffic unknown", num: true, render: (r) => fmt(r.unknown_traffic_endpoints) },
              { key: "v1_requests", label: "v1 requests", num: true, render: (r) => fmt(r.v1_requests) },
              { key: "v2_requests", label: "v2 requests", num: true, render: (r) => fmt(r.v2_requests) },
              { key: "legacy_throttled", label: "Throttled", num: true, render: (r) => fmt(r.legacy_throttled) },
              { key: "v3_requests", label: "Unity Gateway", num: true, render: (r) => fmt(r.v3_requests) },
              { key: "v3_share", label: "Share on Unity Gateway", num: true, render: (r) => pct(r.v3_share) },
              { key: "last_seen", label: "Last legacy request (365 days)", render: (r) => dateOnly(r.last_seen) },
              { key: "due_date", label: "Due", render: (r) => r.due_date ? (
                <>{dateOnly(r.due_date)}<div className="small muted">{r.due_for === "v2" ? "v2 stop" : "v1 retirement"} · {daysLabel(r.due_days_left)}</div></>
              ) : "-" },
            ]} />
          </Card>

          <Card title="Busiest legacy endpoints" note={`Top ${data!.endpoints_limit} of ${fmt(data!.endpoints_total)} legacy endpoints with traffic in the window or the last 365 days. Export for the full list.`}>
            <Table search label="Busiest legacy endpoints" rows={data!.endpoints} empty="No legacy endpoints with traffic in the window or the last 365 days" columns={[
              { key: "workspace_name", label: "Workspace" },
              { key: "endpoint_name", label: "Endpoint", render: (r) => (
                <><code>{r.endpoint_name}</code>{!r.live && <div className="small muted">Deleted; not in live counts</div>}</>) },
              { key: "kind", label: "Kind", render: (r) => String(r.kind).replace(/_/g, " ") },
              { key: "requests", label: "Requests (window)", num: true, render: (r) => fmt(r.requests) },
              { key: "requesters", label: "Callers", num: true, render: (r) => fmt(r.requesters) },
              { key: "throttled", label: "Throttled", num: true, render: (r) => fmt(r.throttled) },
              { key: "last_seen", label: "Last seen", render: (r) => (
                <>{dateOnly(r.last_seen) || "-"}<div className="small muted">{r.traffic_status}</div></>) },
            ]} />
          </Card>

          <Card title="Terms">
            <dl className="small stack-sm" style={{ margin: 0 }}>
              <div><dt><b>Legacy (v1)</b></dt><dd>Requests to legacy serving endpoints, from the endpoint usage system table. May include the backend leg of Unity Gateway calls: the system tables can't tell those apart, so a workspace scan is the check for busy endpoints.</dd></div>
              <div><dt><b>v2</b></dt><dd>AI Gateway v2 calls: rows in the AI Gateway usage table with no service type. Not listed in the schema, so this is inferred from live rows.</dd></div>
              <div><dt><b>Unity Gateway (v3)</b></dt><dd>The target: AI Gateway calls with service type MODEL_SERVICE.</dd></div>
              <div><dt><b>Wave</b></dt><dd>Which group a workspace belongs to, from the traffic (see the wave list above).</dd></div>
              <div><dt><b>Scan</b></dt><dd>A workspace readiness check. A passing scan (READY or READY_WITH_WARNINGS) within the window makes wave 0 ready.</dd></div>
              <div><dt><b>Provisioned Throughput (PT)</b></dt><dd>Dedicated capacity for a foundation model endpoint.</dd></div>
              <div><dt><b>Traffic unknown</b></dt><dd>No usage rows at all for a live endpoint in 365 days. Usage tracking may be off, which the system tables don't show.</dd></div>
            </dl>
          </Card>
        </>
      )}
    </div>
  );
}
