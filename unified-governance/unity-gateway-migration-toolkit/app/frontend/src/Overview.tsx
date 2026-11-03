import { ReactNode, useEffect, useId, useState } from "react";
import { api, fmt, humanize, jobRunning, kindLabel, pct, useApi, useJob } from "./api";
import { Badge, Bars, Card, ErrorBox, ErrorState, ExportMenu, JobLine, Kpi, NavButton, Notice, PageHeader, Reason, SkeletonCard, SkeletonKpis, Table, TrendChart } from "./ui";
import type { Column } from "./ui";

type Workspace = {
  workspace_id: string; workspace_name: string | null; status: string | null; wave: string; readiness: string | null; ready: boolean;
  scan_readiness: string | null; legacy_endpoints: number | null; custom_legacy_endpoints: number | null;
  active_legacy_endpoints: number | null; unknown_traffic_endpoints: number | null; v1_requests: number | null;
  v2_requests: number | null; legacy_requests: number | null; legacy_throttled: number | null;
  deleted_endpoint_requests: number | null; v3_requests: number | null; v3_share: number | null; last_seen: string | null;
  config_signals: string[]; customer_requests: number | null; platform_requests: number | null; coding_agent_requests: number | null;
  legacy_tokens: number | null; v2_failed: number | null; v2_failing: boolean;
};
type Endpoint = {
  workspace_name: string | null; endpoint_name: string; kind: string; live: boolean; requests: number; requesters: number;
  throttled: number; last_seen: string | null; traffic_status: string | null; legacy_tokens: number | null;
};
type OverviewData = {
  snapshot_time: string | null; window_days: number | null; window_assumed: boolean; run_id: string | null;
  running_snapshot: { job_run_id: string; started_at: string | null } | null;
  trend: Record<string, any>[];
  kpis: Record<string, number | null>;
  deadline: { date: string; days_left: number; as_of: string; what: string };
  waves: { wave: string; workspaces: number }[];
  workspaces: Workspace[];
  endpoints: Endpoint[];
  endpoints_limit: number;
  endpoints_total: number;
};

/** Tone per wave. "No legacy traffic" is neutral: it's a candidate until a scan confirms it, not a success. */
const WAVE_TONE = (w: string) =>
  w === "0: traffic unknown" ? "warn" : w === "0: no legacy traffic" || w === "not running" || w === "no legacy endpoints (custom ML only)" ? "neutral" : w.startsWith("0") ? "good"
    : w.startsWith("v2") || w.startsWith("2") ? "bad" : "warn";

const WAVE_LABEL: Record<string, string> = { "0: no legacy traffic": "No legacy traffic (scan to confirm)" };
const waveLabel = (w: string) => WAVE_LABEL[w] || w;

const WAVE_HELP: Record<string, string> = {
  "v2 traffic": "Workspaces with AI Gateway v2 calls on legacy endpoints. Move these first.",
  "2: high volume": "Legacy (v1 and v2) traffic of 10,000 requests or more in the window.",
  "1: small": "Some legacy (v1 and v2) traffic, under 10,000 requests in the window.",
  "1: cleanup": "No legacy traffic, but external model, Provisioned Throughput (PT) or other endpoints still need retiring or applying first.",
  "0: traffic unknown": "Live legacy endpoints with no usage rows in the last 365 days. Usage tracking may be off, so traffic can't be confirmed until a workspace scan.",
  "0: no legacy traffic": "No legacy (v1 and v2) requests in the window. Scan the workspace to confirm before it counts as ready.",
  "no endpoint data": "Nothing for this workspace in the account tables (no endpoints, legacy requests or AI Gateway rows). A workspace scan confirms it.",
  "not running": "The workspace isn't running, so it isn't counted.",
  "no legacy endpoints (custom ML only)": "Only custom ML endpoints: no legacy LLM endpoints to migrate. Pay-per-token calls from code can still exist: scan to confirm.",
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
  const { data, error, loading, reload } = useApi<OverviewData>("/api/overview");
  const config = useApi<any>("/api/config");
  const [jobId, setJobId] = useState<string | null>(null);
  const [startErr, setStartErr] = useState<string | null>(null);
  const [startLink, setStartLink] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const job = useJob(jobId, () => reload());
  const reasonId = useId();

  // A snapshot that was started by someone else (or by the weekly schedule) is shown and polled too.
  const runningId = data?.running_snapshot?.job_run_id ?? null;
  useEffect(() => {
    if (runningId && runningId !== jobId) setJobId(runningId);
  }, [runningId]);

  const running = jobRunning(jobId, job);
  const disabledReason = !operator
    ? "Only operators can start jobs. Ask an operator to refresh the snapshot."
    : running
      ? "A snapshot is already running."
      : starting
        ? "Starting the snapshot."
        : null;

  const refresh = async () => {
    if (disabledReason) return;
    setStartErr(null);
    setStartLink(null);
    setStarting(true);
    try {
      const r = await api("/api/account/snapshot", { method: "POST" });
      setJobId(r.job_run_id);
    } catch (e: any) {
      setStartErr(e.message);
      setStartLink(e.job?.url ?? null);
    } finally {
      setStarting(false);
    }
  };

  const refreshButton = (
    <div className="row">
      <button className="btn" onClick={refresh} aria-disabled={!!disabledReason || undefined}
              aria-describedby={disabledReason ? reasonId : undefined}>
        {starting || running ? "Refreshing…" : "Refresh snapshot"}
      </button>
      {disabledReason && <Reason id={reasonId}>{disabledReason}</Reason>}
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

  return (
    <div className="stack">
      <PageHeader title="Account overview"
                  description={latest && data ? (
                    <>
                      Snapshot taken {ago(data.snapshot_time)} ({utc(data.snapshot_time)}) · rolling {windowLabel} · legacy means v1 and v2
                      {data.running_snapshot?.started_at && running && <> · running since {utc(data.running_snapshot.started_at)}</>}
                    </>
                  ) : undefined}
                  actions={latest ? <>{exports}{refreshButton}</> : undefined} />
      {jobId && <JobLine state={job} label="Snapshot" done="The overview now shows the new snapshot." />}
      {startErr && <ErrorBox error={startErr} title="Couldn't start the snapshot" />}
      {startLink && <p className="small"><a href={startLink} target="_blank" rel="noreferrer">View the running snapshot job</a></p>}

      {loading && !data ? (
        <>
          <SkeletonKpis />
          <div className="grid2"><SkeletonCard title="Traffic" block /><SkeletonCard title="Workspaces by wave" block /></div>
          <SkeletonCard title="Workspaces" />
        </>
      ) : error ? (
        <ErrorState error={error} onRetry={reload} title="Couldn't load the account snapshot" />
      ) : !latest || !data ? (
        <GetStarted refreshButton={refreshButton} />
      ) : (
        <Snapshot data={data} workspaceUrl={config.data?.workspace_url} />
      )}
    </div>
  );
}

/** First run: three steps, in order. The refresh button is the one in the page (no duplicate). */
function GetStarted({ refreshButton }: { refreshButton: ReactNode }) {
  return (
    <Card title="No snapshot yet" note="Three steps, in order. Each step reads this account or workspace; none of them changes a legacy endpoint.">
      <ol className="steps">
        <li>
          <b>1. Refresh snapshot.</b> Reads the account's system tables for every workspace. It takes a few minutes, including job start-up.
          A weekly snapshot runs on a schedule, but it's paused by default.
          {refreshButton}
        </li>
        <li>
          <b>2. Scan this workspace.</b> Reads its endpoints, callers and code, and says whether turning on the Enforce Unity Gateway setting is safe.
          {" "}<NavButton tab="scans" label="Go to Scans" />
        </li>
        <li>
          <b>3. Dry run, then apply.</b> On Apply, dry run the external model and Provisioned Throughput endpoints, then execute the same selection.
          {" "}<NavButton tab="apply" label="Go to Apply" />
        </li>
      </ol>
    </Card>
  );
}

function Snapshot({ data, workspaceUrl }: { data: OverviewData; workspaceUrl?: string }) {
  const windowDays = data.window_days ?? 30;
  const k = data.kpis ?? {};
  const runningCount = k.running_workspaces ?? 0;
  const host = String(workspaceUrl || "").replace(/^https?:\/\//, "").replace(/\/$/, "");
  const waves = data.waves.map((w) => ({ ...w, label: waveLabel(w.wave) }));
  return (
    <>
      <Notice tone="info">
        Other workspaces stay “scan required” until they're scanned from their own install of this app. Scans cover this workspace only{host ? ` (${host})` : ""}.
      </Notice>

      <div className="kpis">
        <Kpi label={`No legacy traffic in ${windowDays} days`} value={`${fmt(k.no_traffic)} of ${fmt(runningCount)}`}
             sub="running workspaces. Scan each one to confirm." />
        <Kpi label="Ready to enforce" value={`${fmt(k.ready)} of ${fmt(runningCount)}`}
             sub="running workspaces with a passing scan in the window" tone={k.ready ? "good" : undefined} />
        <Kpi label="Customer-owned requests" value={fmt(k.customer_requests)}
             sub={k.customer_requests === null || k.customer_requests === undefined
               ? "Refresh the snapshot to see the split"
               : `Your code and jobs, legacy v1 and v2, ${windowDays} days (${fmt(k.active_legacy_endpoints)} active endpoints)`}
             tone={Number(k.customer_requests) ? "bad" : undefined} />
        <Kpi label="Databricks-managed requests" value={fmt(k.platform_requests)}
             sub={Number(k.coding_agent_requests) ? `Databricks features. Coding agents: ${fmt(k.coding_agent_requests)}` : "Databricks features. You can't change these."} />
        <Kpi label="Share on Unity Gateway" value={pct(k.v3_share)} sub={`${fmt(k.v3_requests)} requests`} />
        <Kpi label="Legacy tokens" value={fmt(k.legacy_tokens)} sub={`Input and output, v1 and v2, ${windowDays} days. Shown for sizing; decisions use requests.`} />
        <Kpi label="v2 already failing" value={`${fmt(k.v2_failing_workspaces)} of ${fmt(runningCount)}`}
             sub="running workspaces where most v2 calls already error (v2 is off there). Move those callers first."
             tone={Number(k.v2_failing_workspaces) ? "bad" : undefined} />
        <Kpi label="Days to the legacy deadline" value={daysLabel(data.deadline.days_left)}
             sub={`${dateOnly(data.deadline.date)} · as of ${data.deadline.as_of}`} tone={data.deadline.days_left < 60 ? "bad" : "warn"} />
      </div>
      {k.no_endpoint_data ? (
        <p className="small muted">
          {k.no_endpoint_data === 1 ? "1 running workspace has" : `${fmt(k.no_endpoint_data)} running workspaces have`} no endpoint data, so they aren't in the no-traffic group until a scan confirms them.
        </p>
      ) : null}

      <div className="grid2">
        <Card title="Legacy vs Unity Gateway requests" note={`One point per snapshot; each is a rolling ${windowDays}-day window, so consecutive points overlap.`}>
          <TrendChart label="Legacy vs Unity Gateway requests" points={data.trend}
                      series={[{ key: "legacy_requests", label: "Legacy (v1 and v2)", cls: "legacy" }, { key: "v3_requests", label: "Unity Gateway", cls: "ug" }]} />
          <ViewData label="Legacy vs Unity Gateway requests, by snapshot" rows={data.trend} columns={[
            { key: "snapshot_time", label: "Snapshot", render: (r) => dateOnly(r.snapshot_time) },
            { key: "legacy_requests", label: "Legacy (v1 and v2)", num: true, render: (r) => fmt(r.legacy_requests) },
            { key: "v3_requests", label: "Unity Gateway", num: true, render: (r) => fmt(r.v3_requests) },
          ]} />
        </Card>
        <Card title="Workspaces with no legacy traffic" note="Not the same as ready: each one also needs a passing scan.">
          <TrendChart label="Workspaces with no legacy traffic" points={data.trend} series={[{ key: "no_traffic", label: "No legacy traffic", cls: "single" }]} />
          <ViewData label="Workspaces with no legacy traffic, by snapshot" rows={data.trend} columns={[
            { key: "snapshot_time", label: "Snapshot", render: (r) => dateOnly(r.snapshot_time) },
            { key: "no_traffic", label: "No legacy traffic", num: true, render: (r) => fmt(r.no_traffic) },
            { key: "workspaces", label: "Running workspaces", num: true, render: (r) => fmt(r.workspaces) },
          ]} />
        </Card>
      </div>

      <Card title="Workspaces by migration wave"
            note="Ordered by what to do first. Each workspace is in one wave; a no-traffic workspace counts as ready only after a passing scan.">
        <Bars label="Workspaces by migration wave" rows={waves} labelKey="label" valueKey="workspaces" />
        <ul className="small stack-sm" style={{ paddingLeft: "1.2em" }}>
          {data.waves.map((w) => (
            <li key={w.wave}><Badge value={waveLabel(w.wave)} tone={WAVE_TONE(w.wave)} /> {WAVE_HELP[w.wave] || ""}</li>
          ))}
        </ul>
        <ViewData label="Workspaces by migration wave" rows={waves} columns={[
          { key: "label", label: "Wave" },
          { key: "workspaces", label: "Workspaces", num: true, render: (r) => fmt(r.workspaces) },
        ]} />
      </Card>

      <Card title="Workspaces" note="Busiest first. Customer-owned is your code and jobs; Databricks-managed is Databricks features. On a phone some columns are hidden; Export has them all.">
        <Table search label="Workspaces" rows={data.workspaces} columns={[
          { key: "workspace_name", label: "Workspace", render: (r) => (
            <>
              <b>{r.workspace_name || "-"}</b>
              <div className="muted small">{r.workspace_id}</div>
              {r.config_signals?.length > 0 && (
                <div className="small">Features to check: {r.config_signals.map((s: string) => SIGNAL_LABEL[s] || humanize(s)).join(", ")}</div>
              )}
              {r.v2_failing && <div className="small"><Badge value="v2 failing" tone="bad" /> most v2 calls already error</div>}
            </>) },
          { key: "wave", label: "Wave", render: (r) => (
            <>
              <Badge value={waveLabel(String(r.wave))} tone={WAVE_TONE(String(r.wave))} />
              {r.readiness && <div className={`small ${r.ready ? "" : "muted"}`}>{r.readiness}</div>}
            </>) },
          { key: "legacy_endpoints", label: "Live legacy endpoints", num: true, render: (r) => (
            <>{fmt(r.legacy_endpoints)}{Number(r.custom_legacy_endpoints) > 0 && <div className="small muted">{fmt(r.custom_legacy_endpoints)} external / PT / other</div>}</>) },
          { key: "active_legacy_endpoints", label: "Active", num: true, hideOnPhone: true, render: (r) => fmt(r.active_legacy_endpoints) },
          { key: "unknown_traffic_endpoints", label: "Traffic unknown", num: true, hideOnPhone: true, render: (r) => fmt(r.unknown_traffic_endpoints) },
          { key: "v1_requests", label: "v1 requests", num: true, hideOnPhone: true, render: (r) => fmt(r.v1_requests) },
          { key: "v2_requests", label: "v2 requests", num: true, hideOnPhone: true, render: (r) => fmt(r.v2_requests) },
          { key: "legacy_throttled", label: "Throttled", num: true, hideOnPhone: true, render: (r) => fmt(r.legacy_throttled) },
          { key: "v3_requests", label: "Unity Gateway", num: true, hideOnPhone: true, render: (r) => fmt(r.v3_requests) },
          { key: "v3_share", label: "Share on Unity Gateway", num: true, render: (r) => pct(r.v3_share) },
          { key: "last_seen", label: "Last legacy request (365 days)", hideOnPhone: true, render: (r) => dateOnly(r.last_seen) },
          { key: "customer_requests", label: "Customer-owned", num: true, render: (r) => fmt(r.customer_requests) },
          { key: "platform_requests", label: "Databricks-managed", num: true, hideOnPhone: true, render: (r) => fmt(r.platform_requests) },
          { key: "coding_agent_requests", label: "Coding agents", num: true, hideOnPhone: true, render: (r) => fmt(r.coding_agent_requests) },
        ]} />
      </Card>

      <Card title="Busiest legacy endpoints" note={`Top ${data.endpoints_limit} of ${fmt(data.endpoints_total)} legacy endpoints with traffic in the window or the last 365 days. Export for the full list.`}>
        <Table search label="Busiest legacy endpoints" rows={data.endpoints} empty="No legacy endpoints with traffic in the window or the last 365 days" columns={[
          { key: "workspace_name", label: "Workspace" },
          { key: "endpoint_name", label: "Endpoint", render: (r) => (
            <><code>{r.endpoint_name}</code>{!r.live && <div className="small muted">Deleted; not in live counts</div>}</>) },
          { key: "kind", label: "Kind", render: (r) => kindLabel(r.kind) },
          { key: "requests", label: "Requests (window)", num: true, render: (r) => fmt(r.requests) },
          { key: "legacy_tokens", label: "Tokens (window)", num: true, hideOnPhone: true, render: (r) => fmt(r.legacy_tokens) },
          { key: "requesters", label: "Callers", num: true, hideOnPhone: true, render: (r) => fmt(r.requesters) },
          { key: "throttled", label: "Throttled", num: true, hideOnPhone: true, render: (r) => fmt(r.throttled) },
          { key: "last_seen", label: "Last seen", render: (r) => (
            <>{dateOnly(r.last_seen) || "-"}<div className="small muted">{r.traffic_status}</div></>) },
        ]} />
      </Card>
    </>
  );
}
