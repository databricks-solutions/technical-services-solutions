import { ReactNode, useEffect, useId, useMemo, useState } from "react";
import { api, ageDays, callerLabel, fmt, humanize, isUnknownId, kindLabel, plural, relativeAge, sentence, useApi, useJob, usePollWhileRunning } from "./api";
import { Badge, Card, Confirm, CopyButton, Empty, ErrorBox, ErrorState, ExportLink, HowToEnforce, JobLine, NavButton, Notice, PageHeader, Reason, Skeleton, SkeletonTable, Table, useRunView } from "./ui";
import type { Column } from "./ui";

/* Verify and cut over: the runbook's verify and cut-over steps, in order (1 to 6), run from this page.
 * Every step that changes something is an operator action: a dry run first, then execute with a typed word.
 * Results come from the same run records as Apply; the operation of a run tells the steps apart. */

export const WINDOWS = [["24h", "Last 24 hours"], ["7d", "Last 7 days"], ["30d", "Last 30 days"]] as const;
const API_TYPES = [
  ["mlflow/v1/chat/completions", "Chat completions (default)"],
  ["openai/v1/responses", "Responses"],
  ["mlflow/v1/embeddings", "Embeddings"],
] as const;
const SERVICE_RE = /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/;
const PROMPT_MAX = 200;
const PASSING = ["READY", "READY_WITH_WARNINGS"];

const OPERATION_LABEL: Record<string, string> = {
  test_call: "Test call", pause_legacy: "Pause endpoint", enable_tracking: "Usage tracking", resume_legacy: "Resume",
  apply: "Apply",
};
const ACTION_TONE: Record<string, string> = {
  test_ok: "good", paused: "good", resumed: "good", tracking_enabled: "good", would_test: "info", would_pause: "info",
  would_resume: "info", would_enable_tracking: "info", test_failed: "bad", error: "bad", mismatch: "bad", refused: "warn",
  kept: "warn", already_enabled: "neutral", already_paused: "neutral", already_resumed: "neutral", already_gone: "neutral",
  skipped: "neutral",
};
const ACTION_LABEL: Record<string, string> = {
  test_ok: "Answered", test_failed: "Failed", refused: "Refused", paused: "Paused", resumed: "Resumed",
  tracking_enabled: "Tracking on", already_enabled: "Tracking already on", would_enable_tracking: "Would turn on",
  would_test: "Would test", would_pause: "Would pause", would_resume: "Would resume", already_paused: "Already paused",
  already_resumed: "Already resumed", already_gone: "Endpoint gone", kept: "Kept", skipped: "Skipped", error: "Error",
  mismatch: "Mismatch",
};

/** endpoint_name of legacy requests that couldn't be matched to an endpoint (ug_migration_store.UNATTRIBUTED). */
const UNATTRIBUTED = "(unmatched served entity)";

const stamp = (s: any) => (s ? String(s).replace("T", " ").slice(0, 16) + " UTC" : "-");

/** The query string for a scan: `path?scan_run_id=...` (or the path unchanged when there is no scan). */
const withScan = (path: string, scanId: string) =>
  scanId ? `${path}${path.includes("?") ? "&" : "?"}scan_run_id=${encodeURIComponent(scanId)}` : path;

/** A result row's details, with the pause facts: recent legacy requests, and a write that may have landed. */
function rowDetails(i: any): string {
  const parts = [i.reason || i.note || ""];
  if (typeof i.recent_requests === "number" && i.recent_requests > 0) parts.push(`Legacy requests in the last 24 hours: ${fmt(i.recent_requests)}.`);
  if (i.write_attempted && i.action !== "paused") parts.push("The change may have been written. Resume restores the saved settings.");
  return parts.filter(Boolean).join(" ");
}

/** "test_ok: 2, refused: 1" from a run's summary counts. */
function summaryLine(summary: any): string {
  let s: any = summary;
  if (typeof s === "string") {
    try { s = JSON.parse(s); } catch { s = {}; }
  }
  if (!s || typeof s !== "object") return "";
  return Object.entries(s).filter(([k, v]) => typeof v === "number" && v > 0 && k !== "kept_other_run" && k !== "kept_preexisting" && k !== "not_carried_over")
    .map(([k, v], i) => `${i === 0 ? humanize(k) : humanize(k).toLowerCase()}: ${v}`).join(", ");
}

/* ---------- Status strip: one tile per step, and one step shown at a time ---------- */

const STEPS = [
  ["traffic", "1. Legacy traffic"], ["tracking", "2. Usage tracking"], ["pause", "3. Pause"], ["test", "4. Test call"],
  ["usage", "5. Unity Gateway usage"], ["enforce", "6. Enforce"], ["runs", "Runs"],
] as const;
type StepKey = typeof STEPS[number][0];
type Tile = { status: "done" | "action" | "todo" | "unknown"; value: string };
const TILE_BADGE: Record<Tile["status"], [string, string]> = {
  done: ["Done", "good"], action: ["Needs action", "warn"], todo: ["Not started", "neutral"], unknown: ["Unknown", "bad"],
};

/** The step in the URL hash (#cutover/pause), so a link opens that step. */
function stepFromHash(): StepKey {
  const m = /^#cutover\/([a-z]+)/.exec(window.location.hash || "");
  return (STEPS.find(([k]) => k === m?.[1])?.[0] as StepKey) || "traffic";
}

function StatusStrip({ tiles, next, step, setStep }: {
  tiles: Record<StepKey, Tile | null>; next: string; step: StepKey; setStep: (s: StepKey) => void;
}) {
  const selectId = useId();
  return (
    <section className="card status-strip" aria-label="Cut-over status">
      <h3>Cut-over status</h3>
      <p className="next"><b>What to do next:</b> {next}</p>
      <div className="tiles">
        {STEPS.map(([k, label]) => {
          const t = tiles[k];
          const [badge, tone] = t ? TILE_BADGE[t.status] : ["", "neutral"];
          return (
            <button key={k} type="button" className={`tile${step === k ? " current" : ""}`} data-step={k}
                    aria-pressed={step === k} aria-current={step === k ? "step" : undefined} aria-controls={`cut-step-${k}`}
                    onClick={() => setStep(k)}>
              <span className="tile-title">{label}</span>
              {t && <span className="tile-value small">{t.value}</span>}
              {t && k !== "runs" && <Badge value={badge} tone={tone} />}
            </button>
          );
        })}
      </div>
      <div className="phone-only field-group">
        <label className="field" htmlFor={selectId}>Step</label>
        <select id={selectId} value={step} onChange={(e) => setStep(e.target.value as StepKey)}>
          {STEPS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
        </select>
      </div>
    </section>
  );
}

/** Tiles and the next-step line, from what the page already loaded. */
function cutoverStatus(d: { traffic: any; endpoints: any; runs: any; usage: any; scan: any; enforceTraffic: any; maxAge: number }) {
  const tiles = {} as Record<StepKey, Tile | null>;
  const t = d.traffic;
  const trafficRows: any[] = t.data?.endpoints || [];
  const busy = trafficRows.filter((e) => (e.requests || 0) > 0 && e.endpoint_name !== UNATTRIBUTED);
  const total = t.data?.total_requests;
  tiles.traffic = !t.data && !t.error ? null
    : t.error || t.data?.traffic_error || total === null || total === undefined ? { status: "unknown", value: "Traffic can't be read" }
    : total === 0 ? { status: "done", value: "No legacy requests" }
    : { status: "action", value: busy.length ? `${fmt(total)} requests on ${plural(busy.length, "endpoint")}` : `${fmt(total)} unmatched requests` };
  const track: any[] = (d.endpoints.data?.endpoints || []).filter((e: any) => e.trackable !== false);
  const on = track.filter((e) => e.tracking === "on").length;
  tiles.tracking = !d.endpoints.data ? (d.endpoints.error ? { status: "unknown", value: "Couldn't load endpoints" } : null)
    : track.length === 0 ? { status: "done", value: "Nothing to track" }
    : { status: on === track.length ? "done" : "action", value: `${on} of ${track.length} on` };
  const runs: any[] = d.runs.data || [];
  const paused = runs.filter((r) => r.operation === "pause_legacy" && r.mode === "execute" && r.status === "SUCCEEDED" && !r.resumed);
  const lastPause = runs.find((r) => r.operation === "pause_legacy" && r.mode === "execute");
  tiles.pause = !d.runs.data ? null
    : paused.length ? { status: "done", value: `${plural(paused.length, "endpoint")} paused` }
    : lastPause ? { status: "todo", value: `Last pause ${relativeAge(lastPause.started_at)}, resumed` }
    : { status: "todo", value: "No pause yet" };
  const lastTest = runs.find((r) => r.operation === "test_call" && r.mode === "execute");
  tiles.test = !d.runs.data ? null
    : !lastTest ? { status: "todo", value: "No test call yet" }
    : lastTest.status === "SUCCEEDED" ? { status: "done", value: `Answered, ${relativeAge(lastTest.started_at)}` }
    : ["RUNNING", "STARTING"].includes(lastTest.status) ? { status: "todo", value: "Running" }
    : { status: "action", value: `Failed, ${relativeAge(lastTest.started_at)}` };
  const usageRows: any[] = d.usage.data?.rows || [];
  const ugRequests = usageRows.reduce((n, r) => n + (Number(r.requests) || 0), 0);
  tiles.usage = !d.usage.data ? (d.usage.error ? { status: "unknown", value: "Couldn't load usage" } : null)
    : ugRequests > 0 ? { status: "done", value: `${fmt(ugRequests)} requests in 7 days` }
    : { status: "todo", value: "No requests in 7 days" };
  const age = ageDays(d.scan?.finished_at);
  const scanOk = !!d.scan && PASSING.includes(String(d.scan.readiness)) && (age === null || age <= d.maxAge);
  const et = d.enforceTraffic;
  const quiet = et.data ? et.data.total_requests === 0 : null;
  const blockers = [!scanOk && "the scan doesn't pass", quiet === false && "legacy traffic in the scan's window", et.error && "traffic unknown"].filter(Boolean) as string[];
  tiles.enforce = !d.scan ? { status: "todo", value: "No scan yet" }
    : quiet === null && !et.error ? null
    : blockers.length ? { status: "action", value: plural(blockers.length, "check") + " not met" }
    : { status: "done", value: "Ready to enforce" };
  tiles.runs = !d.runs.data ? null : { status: runs.length ? "done" : "todo", value: plural(runs.length, "run") };
  const next = !d.scan ? "Scan the workspace first: these steps read its plan."
    : tiles.traffic?.status === "unknown" ? "Legacy traffic can't be read: check access to the system tables (step 1)."
    : tiles.tracking?.status === "action" ? `Turn on usage tracking for ${plural(track.length - on, "endpoint")}, so their calls show in the traffic check (step 2).`
    : tiles.traffic?.status === "action" ? (busy.length ? `Traffic is still on ${plural(busy.length, "endpoint")}: move their callers, then pause one at a time (step 3).`
      : "Some legacy requests couldn't be matched to an endpoint: check them in step 1 before you pause anything.")
    : tiles.test?.status !== "done" ? "Test a Unity Gateway service your callers now use (step 4)."
    : tiles.enforce?.status === "action" ? `Not ready to enforce yet: ${blockers.join(", ")} (step 6).`
    : tiles.enforce?.status === "done" ? "Every check passes: turn on Enforce Unity Gateway in the workspace settings (step 6)."
    : "Checking the steps.";
  return { tiles, next };
}

export default function Cutover({ operator, maxScanAgeDays, jobsRunAs, active = true }: { operator: boolean; maxScanAgeDays: number; jobsRunAs?: string | null; active?: boolean }) {
  const scans = useApi<any[]>("/api/scans");
  // Tabs stay mounted: reload the scan list when the tab is opened, so a scan that just finished can be picked.
  useEffect(() => { if (active) scans.reload(); }, [active]); // eslint-disable-line react-hooks/exhaustive-deps
  const succeeded = useMemo(() => (scans.data || []).filter((s) => s.status === "SUCCEEDED"), [scans.data]);
  const [picked, setPicked] = useState<string | null>(null);
  const scan = succeeded.find((s) => s.run_id === picked) || succeeded[0] || null;
  const scanId: string = scan?.run_id || "";
  const runs = useApi<any[]>("/api/cutover/runs");
  const endpoints = useApi<any>(withScan("/api/cutover/endpoints", scanId));
  const services = useApi<any>(withScan("/api/cutover/services", scanId));
  const [win, setWin] = useState("24h");
  const traffic = useApi<any>(withScan(`/api/cutover/traffic?window=${win}`, scanId));
  const enforceTraffic = useApi<any>(withScan("/api/cutover/traffic?window=scan", scanId));
  const reloadAll = () => { runs.reload(); endpoints.reload(); traffic.reload(); };
  const usage = useApi<any>("/api/usage/summary?window=7d&service=");
  const [step, setStepState] = useState<StepKey>(stepFromHash);
  const setStep = (s: StepKey) => {
    setStepState(s);
    window.history.replaceState(null, "", `#cutover/${s}`);
  };
  useEffect(() => { if (active && !window.location.hash.startsWith("#cutover/")) window.history.replaceState(null, "", `#cutover/${step}`); }, [active]); // eslint-disable-line react-hooks/exhaustive-deps
  const status = cutoverStatus({ traffic, endpoints, runs, usage, scan, enforceTraffic, maxAge: maxScanAgeDays });
  // Every step stays mounted (only hidden), so a running dry run keeps polling and Execute stays unlocked.
  const panel = (k: StepKey, node: ReactNode) => <div id={`cut-step-${k}`} hidden={step !== k}>{node}</div>;

  return (
    <div className="stack">
      <PageHeader title="Verify & cut over"
                  description="Check that legacy traffic has stopped, pause legacy endpoints one at a time, test Unity Gateway, then decide to enforce. Operators run the steps that change something. Everyone can read the traffic and the run list; a run's details are for the person who started it, operators and workspace admins." />
      <Card title="Scan used for these steps" note="The endpoints, callers and services come from this scan's plan. Scan again if they've changed.">
        {scans.loading && !scans.data ? <Skeleton lines={1} label="Loading scans" /> : scans.error ? <ErrorState error={scans.error} onRetry={scans.reload} /> : !scan ? (
          <Empty title="No finished scan" action={<NavButton tab="scans" label="Go to Scans" />}>Run a workspace scan first. This page reads its plan.</Empty>
        ) : (
          <div className="stack-sm">
            {succeeded.length > 1 && (
              <div className="stack-sm">
                <label className="field" htmlFor="cut-scan">Scan</label>
                <select id="cut-scan" value={scan.run_id} onChange={(e) => setPicked(e.target.value)}>
                  {succeeded.map((s) => <option key={s.run_id} value={s.run_id}>{stamp(s.finished_at || s.started_at)} · {relativeAge(s.finished_at || s.started_at)} · {String(s.readiness || "unknown").replace(/_/g, " ")}</option>)}
                </select>
              </div>
            )}
            <div className="row small">
              <span>Scan from {relativeAge(scan.finished_at || scan.started_at)}</span>
              <Badge value={scan.readiness || "unknown"} />
              {(ageDays(scan.finished_at) ?? 0) > maxScanAgeDays && <Badge value="older than the limit" tone="warn" />}
            </div>
          </div>
        )}
      </Card>

      <StatusStrip tiles={status.tiles} next={status.next} step={step} setStep={setStep} />
      {panel("traffic", <TrafficCheck traffic={traffic} win={win} setWin={setWin} scanReady={!!scan} />)}
      {panel("tracking", <TrackingStep operator={operator} endpoints={endpoints} scanId={scanId} onDone={reloadAll} />)}
      {panel("pause", <PauseStep operator={operator} endpoints={endpoints} traffic={traffic} win={win} scanId={scanId} runs={runs} onDone={reloadAll} />)}
      {panel("test", <TestStep operator={operator} services={services} scanId={scanId} jobsRunAs={jobsRunAs} onDone={runs.reload} />)}
      {panel("usage", <UsageStep />)}
      {panel("enforce", <EnforceStep scan={scan} enforceTraffic={enforceTraffic} maxAge={maxScanAgeDays} />)}
      {panel("runs", <RunHistory operator={operator} runs={runs} />)}
    </div>
  );
}

/* ---------- Shared: start a run, show its progress and results ---------- */

export type Started = { applyId: string; jobRunId: string; mode: "dry_run" | "execute"; operation: string; sig: string; runsAs?: string | null };

/** Starts a verify or cut-over run (POST /api/cutover). A 409 naming another run keeps its job link; other 409s
 *  (traffic on the endpoint, a dry run that changed or expired) show their reason. */
function useCutoverRun() {
  const [run, setRun] = useState<Started | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [conflict, setConflict] = useState<{ job: { job_run_id: string; url: string | null } | null } | null>(null);
  const start = async (body: Record<string, any>, sig: string): Promise<boolean> => {
    setBusy(true);
    setErr(null);
    setConflict(null);
    try {
      const r: any = await api("/api/cutover", { method: "POST", body: JSON.stringify(body) });
      setRun({ applyId: r.apply_id, jobRunId: r.job_run_id, mode: body.mode, operation: body.operation, sig, runsAs: r.runs_as ?? null });
      return true;
    } catch (e: any) {
      if (e.status === 409 && e.job) setConflict({ job: e.job });
      else setErr(e.message);
      return false;
    } finally {
      setBusy(false);
    }
  };
  return { run, busy, err, conflict, start };
}

/** A run's progress, then its results once it ends. onDone runs once when the run reaches a final status. */
function RunResult({ started, label, onDone, columns }: {
  started: Started | null; label: string; onDone?: (meta: any, started: Started | null) => void; columns?: Column<any>[];
}) {
  const id = started?.applyId ?? null;
  const { data, error, reload } = useApi<any>(id ? `/api/cutover/${id}` : null);
  const job = useJob(started?.jobRunId ?? null);
  usePollWhileRunning(data?.meta?.status, error, reload);
  const status = data?.meta?.status;
  useEffect(() => {
    if (status && status !== "RUNNING" && status !== "STARTING") onDone?.(data.meta, started);
    // Fires once per status change to a final status; the callback reads the latest run through the props it was given.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);
  if (!started) return null;
  if (isUnknownId(error)) return <Notice tone="warning" title="This run doesn't exist">It may have been removed.</Notice>;
  if (!data || status === "RUNNING" || status === "STARTING") {
    return (
      <div className="stack-sm">
        <JobLine state={job} label={label} done="The results are below." />
        {error ? <ErrorState error={error} onRetry={reload} title="Couldn't load this run" /> : <Skeleton lines={2} label={`Waiting for ${label.toLowerCase()} results`} />}
      </div>
    );
  }
  if (error) return <ErrorState error={error} onRetry={reload} title="Couldn't load this run" />;
  const m = data.meta;
  const tone = m.status === "SUCCEEDED" ? "success" : m.status === "NEEDS_ATTENTION" ? "warning" : "error";
  const summary = summaryLine(m.summary);
  return (
    <div className="stack-sm">
      <Notice tone={tone} title={`${label}: ${String(m.status).toLowerCase().replace("_", " ")}`}>
        {summary || (m.status === "FAILED" ? m.error || "The job ended without recording a result." : null)}
        {m.status === "NEEDS_ATTENTION" && <> Check the rows marked refused, failed or error below: each one says why.</>}
      </Notice>
      <Table label={`${label} results`} rows={data.items} pageSize={50} columns={columns || [
        { key: "name", label: "Target", render: (i) => <code className="wrap">{i.name}</code> },
        { key: "action", label: "Result", render: (i) => <Badge value={ACTION_LABEL[i.action] || humanize(i.action)} tone={ACTION_TONE[i.action] || "neutral"} /> },
        { key: "reason", label: "Details", sortable: false, render: (i) => <span className="small">{rowDetails(i)}</span> },
      ]} empty={<Empty title="No results">This run didn't check anything.</Empty>} />
    </div>
  );
}

/** The dry run and execute pair. Execute needs a successful dry run of the same settings and the typed word. */
function DryRunPair({ operator, disabledReason, dry, sig, word, label, confirmTitle, confirmAction, confirmBody, onDryRun, onExecute, busy, id }: {
  operator: boolean; disabledReason: string | null; dry: { applyId: string; sig: string } | null; sig: string;
  word: string; label: string; confirmTitle: string; confirmAction: string; confirmBody: ReactNode;
  onDryRun: () => void; onExecute: () => void; busy: boolean; id: string;
}) {
  const [confirming, setConfirming] = useState(false);
  const dryOk = !!dry && dry.sig === sig;
  const reasons = [!operator && "Only operators can start this.", disabledReason].filter(Boolean) as string[];
  const execReasons = [...reasons, !dryOk && `Run a dry run of these settings first.`].filter(Boolean) as string[];
  // View-only users get the reason, not action buttons (the brief: view-only sees no action buttons).
  if (!operator) return <Reason id={`${id}-dry`}>Only operators can run this step. You can read the results below.</Reason>;
  return (
    <div className="stack-sm">
      <div className="row">
        <button className="btn" aria-disabled={reasons.length > 0 || busy || undefined}
                aria-describedby={reasons.length ? `${id}-dry` : undefined}
                onClick={() => { if (!reasons.length && !busy) onDryRun(); }}>
          {busy ? "Starting…" : "Dry run"}
        </button>
        <button className="btn danger" aria-disabled={execReasons.length > 0 || busy || undefined}
                aria-describedby={execReasons.length ? `${id}-exec` : undefined}
                onClick={() => { if (!execReasons.length && !busy) setConfirming(true); }}>
          Execute…
        </button>
      </div>
      {reasons.length > 0 && <Reason id={`${id}-dry`}>Dry run is unavailable. {reasons.join(" ")}</Reason>}
      {reasons.length === 0 && execReasons.length > 0 && <Reason id={`${id}-exec`}>Execute is unavailable. {execReasons.join(" ")}</Reason>}
      {dryOk && reasons.length === 0 && <p className="small">Dry run checked. Execute does exactly what it showed.</p>}
      {confirming && (
        <Confirm word={word} title={confirmTitle} action={confirmAction} busy={busy} body={confirmBody}
                 onCancel={() => setConfirming(false)} onConfirm={() => { setConfirming(false); onExecute(); }} />
      )}
    </div>
  );
}

function ConflictNotice({ job }: { job: { job_run_id: string; url: string | null } | null }) {
  return (
    <Notice tone="info" action={job?.url ? <a className="btn link sm" href={job.url} target="_blank" rel="noreferrer">View job run</a> : undefined}>
      Another verify, cut-over or apply run is already running. Wait for it to finish, then try again.
    </Notice>
  );
}

/* ---------- 1. Legacy traffic ---------- */

function TrafficCheck({ traffic, win, setWin, scanReady }: { traffic: any; win: string; setWin: (w: string) => void; scanReady: boolean }) {
  const selectId = useId();
  const since = traffic.data?.since ? stamp(traffic.data.since) : null;
  const rows: any[] = traffic.data?.endpoints || [];
  return (
    <Card title="1. Legacy traffic" note="Requests to each legacy endpoint (v1 and v2) since the time shown, and who sent them. Zero for the whole window is the check before you pause anything.">
      <div className="row">
        <div className="field-group">
          <label className="field" htmlFor={selectId}>Window</label>
          <select id={selectId} value={win} onChange={(e) => setWin(e.target.value)}>
            {WINDOWS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </div>
        <button className="btn secondary sm" onClick={traffic.reload} aria-disabled={traffic.loading || undefined}>{traffic.loading ? "Checking…" : "Check again"}</button>
      </div>
      {!scanReady ? <Empty title="No scan yet">Scan the workspace first; the endpoints come from its plan.</Empty>
        : traffic.loading && !traffic.data ? <SkeletonTable rows={4} label="Checking legacy traffic" />
        : traffic.error ? <ErrorState error={traffic.error} onRetry={traffic.reload} title="Couldn't check traffic" />
        : traffic.data?.traffic_error ? (
          <Notice tone="error" title="Traffic is unknown">
            {traffic.data.traffic_error} Until it can be read, the toolkit doesn't treat any endpoint as quiet, and pausing stays off.
          </Notice>)
        : rows.length === 0 ? <Empty title="No legacy endpoints in this scan">Nothing to check.</Empty>
        : (
          <>
            <p className="small">
              {traffic.data.total_requests ? <><b>{fmt(traffic.data.total_requests)}</b> legacy requests since {since}. Callers still on an endpoint get errors once it's paused.</>
                : <>No legacy requests since {since}, across {plural(rows.length, "endpoint")}.</>}
            </p>
            <Table search label="Legacy traffic by endpoint" rows={rows} columns={[
              { key: "endpoint_name", label: "Endpoint", render: (e) => (
                <>{e.endpoint_name === UNATTRIBUTED ? <span>Unmatched requests <span className="small muted">(could be any endpoint)</span></span> : <code>{e.endpoint_name}</code>}{e.kind === "v2_workspace_endpoint" && <> <Badge value="v2" tone="warn" /></>}
                  {e.v2_failing && <> <Badge value="Failing" tone="bad" /></>}</>) },
              { key: "requests", label: "Requests", num: true, render: (e) => <>{fmt(e.requests)}{e.v2_failing && <div className="small muted">{fmt(e.v2_failed)} failed</div>}</> },
              { key: "tokens", label: "Tokens", num: true, hideOnPhone: true, render: (e) => fmt(e.tokens) },
              { key: "last_request", label: "Last request", render: (e) => <span className="small">{e.last_request ? stamp(e.last_request) : "-"}</span> },
              { key: "status", label: "Status", sortable: false, render: (e) => e.status === "no_requests"
                ? <Badge value="No requests" tone="good" />
                : <Badge value="Traffic in window" tone="bad" /> },
              { key: "callers", label: "Callers", sortable: false, render: (e) => (e.callers || []).length === 0 ? <span className="muted small">None</span> : (
                <ul className="small" style={{ margin: 0, paddingLeft: "1.1em" }}>
                  {e.callers.slice(0, 4).map((c: any, i: number) => (
                    <li key={i}>{c.requester} · {callerLabel(c.caller_class)} · {fmt(c.requests)}</li>
                  ))}
                  {e.callers.length > 4 && <li>and {e.callers.length - 4} more</li>}
                </ul>) },
            ]} />
          </>
        )}
    </Card>
  );
}

/* ---------- 2. Usage tracking ---------- */

function TrackingStep({ operator, endpoints, scanId, onDone }: { operator: boolean; endpoints: any; scanId: string; onDone: () => void }) {
  const list: any[] = (endpoints.data?.endpoints || []).filter((e: any) => e.trackable !== false);
  const off = list.filter((e) => e.tracking !== "on");
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const runner = useCutoverRun();
  const [dry, setDry] = useState<{ applyId: string; sig: string } | null>(null);
  const picked = [...chosen].filter((n) => off.some((e) => e.endpoint === n)).sort();
  const sig = JSON.stringify({ op: "enable_tracking", e: picked });
  const body = (mode: "dry_run" | "execute", dryId = "") => ({
    operation: "enable_tracking", mode, endpoints: picked, scan_run_id: scanId, dry_run_id: dryId,
    confirm: mode === "execute" ? "ENABLE" : "",
  });
  const toggle = (name: string, on: boolean) => {
    const s = new Set(chosen);
    if (on) s.add(name); else s.delete(name);
    setChosen(s);
  };
  const disabled = !picked.length ? "Choose at least one endpoint." : runner.busy ? "A run is starting." : null;
  return (
    <Card title="2. Turn on usage tracking" note="Usage tracking records each call to an endpoint in the system tables, so the traffic check can see it. It changes only the usage tracking setting.">
      {endpoints.loading && !endpoints.data ? <SkeletonTable rows={3} label="Loading endpoints" />
        : endpoints.error ? <ErrorState error={endpoints.error} onRetry={endpoints.reload} title="Couldn't load endpoints" />
        : list.length === 0 ? <Empty title="No endpoints to change">This scan has no v1 endpoints to turn tracking on for.</Empty>
        : (
          <>
            <p className="small muted">{plural(off.length, "endpoint")} with tracking off or not checked yet. A dry run shows the current state of each one.</p>
            <Table label="Endpoints and usage tracking" rows={list} search pageSize={50}
                   tools={<span className="small muted" aria-live="polite">{picked.length} selected</span>} columns={[
              { key: "pick", label: "Turn on", sortable: false, width: "72px", render: (e) => (
                <input type="checkbox" aria-label={`Turn on usage tracking for ${e.endpoint}`} disabled={e.tracking === "on" || !operator}
                       checked={chosen.has(e.endpoint)} onChange={(ev) => toggle(e.endpoint, ev.target.checked)} />) },
              { key: "endpoint", label: "Endpoint", render: (e) => <code>{e.endpoint}</code> },
              { key: "kind", label: "Kind", hideOnPhone: true, render: (e) => kindLabel(e.kind) },
              { key: "tracking", label: "Tracking", render: (e) => e.tracking === "on" ? <Badge value="On" tone="good" />
                : e.tracking === "off" ? <Badge value="Off" tone="warn" /> : <Badge value="Not checked" tone="neutral" /> },
            ]} />
            <DryRunPair id="track" operator={operator} disabledReason={disabled} dry={dry} sig={sig} word="ENABLE" label="Usage tracking"
              confirmTitle="Turn on usage tracking" confirmAction={`Turn on ${plural(picked.length, "endpoint")}`} busy={runner.busy}
              confirmBody={<>
                <p>Turn usage tracking on for {picked.map((n) => <code key={n} className="wrap">{n} </code>)}</p>
                <p className="small">Only the usage tracking setting changes. Endpoints that already track are skipped.</p>
              </>}
              onDryRun={async () => { const ok = await runner.start(body("dry_run"), sig); if (!ok) setDry(null); }}
              onExecute={() => { runner.start(body("execute", dry?.applyId || ""), sig); }} />
            <RunResult key={runner.run?.applyId} started={runner.run?.operation === "enable_tracking" ? runner.run : null} label="Usage tracking"
              onDone={(m, s) => {
                if (s?.mode === "dry_run" && m.status === "SUCCEEDED") setDry({ applyId: s.applyId, sig: s.sig });
                if (s?.mode === "execute") onDone();
              }} />
            {runner.err && <ErrorBox error={runner.err} title="Couldn't start the run" />}
            {runner.conflict && <ConflictNotice job={runner.conflict.job} />}
          </>
        )}
    </Card>
  );
}

/* ---------- 3. Pause a legacy endpoint ---------- */

function PauseStep({ operator, endpoints, traffic, win, scanId, runs, onDone }: {
  operator: boolean; endpoints: any; traffic: any; win: string; scanId: string; runs: any; onDone: () => void;
}) {
  const list: any[] = (endpoints.data?.endpoints || []).filter((e: any) => e.kind !== "v2_workspace_endpoint");
  const [name, setName] = useState("");
  const [ack, setAck] = useState(false);
  const selectId = useId();
  const current = (traffic.data?.endpoints || []).find((e: any) => e.endpoint_name === name);
  // Requests that can't be matched to an endpoint could be this one's, so they count as traffic here (the server agrees).
  const unmatched = Number((traffic.data?.endpoints || []).find((e: any) => e.endpoint_name === UNATTRIBUTED)?.requests) || 0;
  const hasTraffic = (!!current && current.requests > 0) || (!!name && unmatched > 0);
  const runner = useCutoverRun();
  const [dry, setDry] = useState<{ applyId: string; sig: string } | null>(null);
  const sig = JSON.stringify({ op: "pause_legacy", e: name, f: hasTraffic && ack });  // ack is the job's force flag, part of the fingerprint
  const body = (mode: "dry_run" | "execute", dryId = "") => ({
    operation: "pause_legacy", mode, endpoints: [name], scan_run_id: scanId, dry_run_id: dryId,
    confirm: mode === "execute" ? "PAUSE" : "", traffic_window: win, ack_traffic: hasTraffic && ack,
  });
  // The server checks the same traffic again before it starts the run, and refuses when it can't read it.
  const trafficUnknown = !traffic.data || !!traffic.data.traffic_error || !!traffic.error || (!!name && !current);
  const disabled = !name ? "Choose an endpoint." : trafficUnknown ? "Traffic for this endpoint isn't known yet (see step 1)." : hasTraffic && !ack ? "Confirm that callers still on this endpoint will get errors." : runner.busy ? "A run is starting." : null;
  const resumable: any[] = (runs.data || []).filter((r: any) => r.operation === "pause_legacy" && r.mode === "execute"
    && ["SUCCEEDED", "NEEDS_ATTENTION", "FAILED"].includes(r.status) && !r.resumed);
  const [resuming, setResuming] = useState<any | null>(null);
  const resume = useCutoverRun();
  const windowLabel = WINDOWS.find(([k]) => k === win)?.[1]?.toLowerCase() || win;

  return (
    <Card title="3. Pause a legacy endpoint, one at a time" note="Pausing sets the endpoint's rate limit to 0 calls a minute. Resume puts back the settings it had before the pause.">
      <Notice tone="warning" title="Callers still on this endpoint get errors">
        Every request to a paused endpoint fails until you resume it. Pause only after the traffic check shows no requests, or once the callers have moved. A paused <code>databricks-*</code> endpoint stops for everyone in this workspace, so tell its users first.
      </Notice>
      {endpoints.loading && !endpoints.data ? <SkeletonTable rows={2} label="Loading endpoints" />
        : endpoints.error ? <ErrorState error={endpoints.error} onRetry={endpoints.reload} title="Couldn't load endpoints" />
        : list.length === 0 ? <Empty title="No endpoint to pause">This scan has no v1 endpoint to pause.</Empty>
        : (
          <div className="stack-sm">
            <div className="field-group">
              <label className="field" htmlFor={selectId}>Legacy endpoint</label>
              <select id={selectId} value={name} disabled={!operator} onChange={(e) => { setName(e.target.value); setAck(false); setDry(null); }}>
                <option value="">Choose an endpoint</option>
                {list.map((e: any) => <option key={e.endpoint} value={e.endpoint}>{e.endpoint}</option>)}
              </select>
            </div>
            {name && (traffic.data && !traffic.data.traffic_error && current ? (
              hasTraffic ? (
                <Notice tone="warning" title={current.requests > 0 ? `${fmt(current.requests)} requests in the ${windowLabel}` : `${fmt(unmatched)} unmatched requests in the ${windowLabel}`}>
                  {current.requests > 0 ? <>Last request {stamp(current.last_request)}. Callers still on it get errors. Move them first, or confirm below.</>
                    : <>They couldn't be matched to an endpoint, so some could be calling this one. Check them first, or confirm below.</>}
                  {current.requests > 0 && unmatched > 0 && <> Another {fmt(unmatched)} requests couldn't be matched to an endpoint and could be this one's too.</>}
                </Notice>
              ) : (
                <Notice tone="success" title={`No legacy requests since ${stamp(traffic.data.since)}`}>This endpoint is quiet for the {windowLabel}.</Notice>
              )
            ) : traffic.loading ? <p className="small muted">Checking traffic for this endpoint…</p>
              : <p className="small muted">Traffic for this endpoint couldn't be read, so it can't be paused from here. See step 1.</p>)}
            {hasTraffic && (
              <label className="choice"><input type="checkbox" checked={ack} disabled={!operator} onChange={(e) => setAck(e.target.checked)} />
                <span>I understand callers still on this endpoint will get errors until it's resumed</span></label>
            )}
            {!name && <p className="small muted">Choose an endpoint to see its traffic and enable the dry run.</p>}
            <DryRunPair id="pause" operator={operator} disabledReason={disabled} dry={dry} sig={sig} word="PAUSE" label="Pause"
              confirmTitle={`Pause ${name}`} confirmAction={`Pause ${name}`} busy={runner.busy}
              confirmBody={<>
                <p>Endpoint to pause: <strong><code>{name}</code></strong></p>
                <p>It is set to 0 calls a minute. Requests to it fail until it's resumed.</p>
                {hasTraffic && <Notice tone="warning">{current && current.requests > 0 ? `It had ${fmt(current.requests)} requests in the ${windowLabel}.` : `${fmt(unmatched)} requests in the ${windowLabel} couldn't be matched to an endpoint and could be this one's.`}</Notice>}
              </>}
              onDryRun={async () => { const ok = await runner.start(body("dry_run"), sig); if (!ok) setDry(null); }}
              onExecute={() => { runner.start(body("execute", dry?.applyId || ""), sig); }} />
            <RunResult key={runner.run?.applyId} started={runner.run?.operation === "pause_legacy" ? runner.run : null} label="Pause"
              onDone={(m, s) => {
                if (s?.mode === "dry_run" && m.status === "SUCCEEDED") setDry({ applyId: s.applyId, sig: s.sig });
                if (s?.mode === "execute") onDone();
              }} />
            {runner.err && <ErrorBox error={runner.err} title="Couldn't start the run" />}
            {runner.conflict && <ConflictNotice job={runner.conflict.job} />}
          </div>
        )}
      {resumable.length > 0 && (
        <div className="panel stack-sm">
          <p className="small"><b>Paused by a run.</b> Resume puts the settings back as they were before the pause.</p>
          <Table label="Paused endpoints you can resume" rows={resumable} columns={[
            { key: "endpoints", label: "Endpoint", render: (r) => <code>{r.endpoints}</code> },
            { key: "started_at", label: "Paused", render: (r) => <span className="small">{stamp(r.started_at)}</span> },
            { key: "status", label: "Result", render: (r) => <Badge value={r.status} /> },
            { key: "resume", label: "", sortable: false, render: (r) => (
              operator ? <button className="btn secondary sm" aria-disabled={resume.busy || undefined}
                      onClick={() => { if (!resume.busy) setResuming(r); }}>Resume…</button> : <span className="small muted">Operators only</span>) },
          ]} />
          {resuming && (
            <Confirm word="RESUME" title={`Resume ${resuming.endpoints}`} action="Resume endpoint" busy={resume.busy}
                     onCancel={() => setResuming(null)}
                     onConfirm={async () => {
                       const ok = await resume.start({ operation: "resume_legacy", mode: "execute", rollback_of: resuming.apply_id, confirm: "RESUME" }, "");
                       if (ok) { setResuming(null); onDone(); }
                     }}
                     body={<p>Restore <code>{resuming.endpoints}</code>'s settings from before the pause. Callers can send requests to it again.</p>} />
          )}
          <RunResult key={resume.run?.applyId} started={resume.run?.operation === "resume_legacy" ? resume.run : null} label="Resume" onDone={() => onDone()} />
          {resume.err && <ErrorBox error={resume.err} title="Couldn't start the resume" />}
        </div>
      )}
    </Card>
  );
}

/* ---------- 4. Test call ---------- */

function TestStep({ operator, services, scanId, jobsRunAs, onDone }: { operator: boolean; services: any; scanId: string; jobsRunAs?: string | null; onDone: () => void }) {
  const listed: any[] = services.data?.services || [];
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [extra, setExtra] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const [draftErr, setDraftErr] = useState<string | null>(null);
  const [apiType, setApiType] = useState<string>(API_TYPES[0][0]);
  const [prompt, setPrompt] = useState("Reply with: ok");
  const runner = useCutoverRun();
  const [dry, setDry] = useState<{ applyId: string; sig: string } | null>(null);
  const names = [...new Set([...chosen, ...extra])].sort();
  const promptOk = prompt.length <= PROMPT_MAX && !/[\n\r\t]/.test(prompt);
  const sig = JSON.stringify({ op: "test_call", s: names, a: apiType, p: prompt });
  const promptId = useId();
  const addId = useId();
  const apiId = useId();
  const body = (mode: "dry_run" | "execute", dryId = "") => ({
    operation: "test_call", mode, services: names, api_type: apiType, prompt, scan_run_id: scanId, dry_run_id: dryId,
    confirm: mode === "execute" ? "TEST" : "",
  });
  const add = () => {
    const v = draft.trim();
    if (!SERVICE_RE.test(v)) { setDraftErr("Use catalog.schema.name, with letters, digits, _ and -."); return; }
    setDraftErr(null);
    if (!extra.includes(v) && !listed.some((s: any) => s.name === v)) setExtra([...extra, v]);
    setDraft("");
  };
  const disabled = !names.length ? "Choose at least one service." : !promptOk ? "The prompt must be one line of up to 200 characters." : runner.busy ? "A run is starting." : null;
  return (
    <Card title="4. Test a Unity Gateway service" note="One small request per service, so each one is billable. A dry run only checks that the services exist.">
      <p className="small">
        The test call runs as the apply job's identity{jobsRunAs ? <> (<code>{jobsRunAs}</code>)</> : null}, not as you. It shows that the service answers; it doesn't show that you or your callers have access. Usage rows for it name that identity as the requester.
      </p>
      {services.loading && !services.data ? <SkeletonTable rows={2} label="Loading services" />
        : services.error ? <ErrorState error={services.error} onRetry={services.reload} title="Couldn't load services" />
        : (
          <div className="stack">
            {listed.length === 0 ? <p className="small muted">The scan plans no Unity Gateway services. Add one by name below.</p> : (
              <fieldset className="panel">
                <legend>Services from the scan plan</legend>
                {listed.map((s: any) => (
                  <label key={s.name} className="choice">
                    <input type="checkbox" checked={chosen.has(s.name)} disabled={!operator}
                           onChange={(e) => { const c = new Set(chosen); if (e.target.checked) c.add(s.name); else c.delete(s.name); setChosen(c); }} />
                    <span><code>{s.name}</code> {s.exists && <Badge value="exists" tone="good" />} <span className="small muted">from {s.from}</span></span>
                  </label>
                ))}
              </fieldset>
            )}
            <div className="field-group">
              <label className="field" htmlFor={addId}>Add a service by name</label>
              <div className="row">
                <input id={addId} placeholder="system.ai.gpt-5-mini" value={draft} disabled={!operator} aria-invalid={!!draftErr}
                       aria-describedby={draftErr ? `${addId}-err` : undefined} onChange={(e) => setDraft(e.target.value)}
                       onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }} />
                {operator && <button className="btn secondary sm" onClick={add}>Add</button>}
              </div>
              {draftErr && <span id={`${addId}-err`} className="field-error">{draftErr}</span>}
              {extra.length > 0 && (
                <ul className="small" style={{ paddingLeft: "1.1em" }}>
                  {extra.map((s) => <li key={s}><code>{s}</code> <button className="btn link sm" aria-label={`Remove ${s}`} disabled={!operator} onClick={() => setExtra(extra.filter((x) => x !== s))}>Remove</button></li>)}
                </ul>
              )}
            </div>
            <div className="field-group">
              <label className="field" htmlFor={apiId}>API type</label>
              <select id={apiId} value={apiType} onChange={(e) => setApiType(e.target.value)} disabled={!operator}>
                {API_TYPES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
            </div>
            <div className="field-group">
              <label className="field" htmlFor={promptId}>Prompt</label>
              <input id={promptId} value={prompt} maxLength={PROMPT_MAX} disabled={!operator} aria-describedby={`${promptId}-count`}
                     onChange={(e) => setPrompt(e.target.value)} />
              <span id={`${promptId}-count`} className={`small ${promptOk ? "muted" : "text-bad"}`}>{prompt.length} of {PROMPT_MAX} characters, one line</span>
            </div>
            <DryRunPair id="test" operator={operator} disabledReason={disabled} dry={dry} sig={sig} word="TEST" label="Test call"
              confirmTitle="Test call" confirmAction={`Send ${plural(names.length, "request")}`} busy={runner.busy}
              confirmBody={<>
                <p>Send one small request to each of: {names.map((n) => <code key={n} className="wrap">{n} </code>)}</p>
                <p className="small">Each request is billable. Its usage appears in 20 to 30 minutes; the results include a request id to check.</p>
              </>}
              onDryRun={async () => { const ok = await runner.start(body("dry_run"), sig); if (!ok) setDry(null); }}
              onExecute={() => { runner.start(body("execute", dry?.applyId || ""), sig); }} />
            <RunResult key={runner.run?.applyId} started={runner.run?.operation === "test_call" ? runner.run : null} label="Test call"
              onDone={(m, s) => {
                if (s?.mode === "dry_run" && m.status === "SUCCEEDED") setDry({ applyId: s.applyId, sig: s.sig });
                if (s?.mode === "execute") onDone();
              }}
              columns={[
                { key: "name", label: "Service", render: (i) => <code className="wrap">{i.name}</code> },
                { key: "action", label: "Result", render: (i) => <Badge value={ACTION_LABEL[i.action] || humanize(i.action)} tone={ACTION_TONE[i.action] || "neutral"} /> },
                { key: "http_status", label: "HTTP", num: true, hideOnPhone: true, render: (i) => fmt(i.http_status) },
                { key: "latency_ms", label: "Latency", num: true, hideOnPhone: true, render: (i) => (i.latency_ms === undefined || i.latency_ms === null ? "-" : `${fmt(i.latency_ms)} ms`) },
                { key: "reply_excerpt", label: "Reply", sortable: false, render: (i) => <span className="small">{i.reply_excerpt || i.reason || ""}</span> },
                { key: "request_id", label: "Request id", sortable: false, render: (i) => i.request_id ? (
                  <div className="stack-sm">
                    <code className="wrap small">{i.request_id}</code>
                    <div className="row"><CopyButton text={i.request_id} label="Copy id" /><UsageCheck requestId={i.request_id} /></div>
                  </div>) : <span className="muted small">{i.note || "-"}</span> },
              ]} />
            {runner.err && <ErrorBox error={runner.err} title="Couldn't start the test" />}
            {runner.conflict && <ConflictNotice job={runner.conflict.job} />}
          </div>
        )}
    </Card>
  );
}

/** "Check usage" for one request id (runbook cell 14). Usage takes 20 to 30 minutes to appear. */
function UsageCheck({ requestId }: { requestId: string }) {
  const [state, setState] = useState<{ loading: boolean; rows: any[] | null; error: string | null }>({ loading: false, rows: null, error: null });
  const check = () => {
    setState({ loading: true, rows: null, error: null });
    api<any>(`/api/usage/request?request_id=${encodeURIComponent(requestId)}`)
      .then((r) => setState({ loading: false, rows: r.rows || [], error: null }))
      .catch((e) => setState({ loading: false, rows: null, error: String(e.message || e) }));
  };
  return (
    <div className="stack-sm">
      <button className="btn secondary sm" onClick={check} aria-disabled={state.loading || undefined}>{state.loading ? "Checking…" : "Check usage"}</button>
      {state.error && <ErrorBox error={state.error} title="Couldn't check usage" />}
      {state.rows && state.rows.length === 0 && (
        <p className="small muted">No usage rows yet. Usage takes 20 to 30 minutes to appear after a call, so check again later.</p>
      )}
      {state.rows && state.rows.length > 0 && (
        <Table label={`Usage for request ${requestId.slice(0, 8)}`} rows={state.rows} columns={[
          { key: "event_time", label: "Time", render: (r) => <span className="small">{stamp(r.event_time)}</span> },
          { key: "service_name", label: "Service", render: (r) => <code className="small">{r.service_name}</code> },
          { key: "destination_model", label: "Model", hideOnPhone: true },
          { key: "status_code", label: "Status", num: true, render: (r) => fmt(r.status_code) },
          { key: "total_tokens", label: "Tokens", num: true, render: (r) => fmt(r.total_tokens) },
          { key: "latency_ms", label: "Latency", num: true, hideOnPhone: true, render: (r) => `${fmt(r.latency_ms)} ms` },
        ]} />
      )}
    </div>
  );
}

/* ---------- 5. Unity Gateway traffic ---------- */

function UsageStep() {
  const [win, setWin] = useState("7d");
  const [service, setService] = useState("");
  const services = useApi<any>("/api/cutover/services");
  const rows = useApi<any>(`/api/usage/summary?window=${win}&service=${encodeURIComponent(service)}`);
  const winId = useId();
  const svcId = useId();
  const list: any[] = rows.data?.rows || [];
  const exportHref = `/api/usage/summary/export?window=${win}&service=${encodeURIComponent(service)}`;
  const cols: Column<any>[] = [
    { key: "service_name", label: "Service", render: (r) => <code className="small">{r.service_name}</code> },
    ...(new Set(list.map((r) => r.workspace_id)).size > 1
      ? [{ key: "workspace_id", label: "Workspace", hideOnPhone: true, render: (r: any) => <span className="small">{r.workspace_id}</span> }]
      : []),
    { key: "requester", label: "Requester", render: (r) => <span className="small">{r.requester}</span> },
    { key: "api_type", label: "API type", hideOnPhone: true, render: (r) => <span className="small">{r.api_type}</span> },
    { key: "destination_model", label: "Destination", hideOnPhone: true, render: (r) => <span className="small">{r.destination_model}</span> },
    { key: "requests", label: "Requests", num: true, render: (r) => fmt(r.requests) },
    { key: "total_tokens", label: "Tokens", num: true, render: (r) => fmt(r.total_tokens) },
    { key: "p95_latency_ms", label: "Latency ms, avg / p95", num: true, hideOnPhone: true,
      render: (r) => <span className="small">{fmt(r.average_latency_ms)} / {fmt(r.p95_latency_ms)}</span> },
    { key: "error_invocations", label: "Errors", num: true, render: (r) => fmt(r.error_invocations) },
    { key: "last_request", label: "Last request", render: (r) => <span className="small">{stamp(r.last_request)}</span> },
  ];
  return (
    <Card title="5. Unity Gateway traffic" note="Model Service calls through Unity Gateway, per service, workspace, requester, API type and destination. Usage can lag 20 to 30 minutes. The CSV adds invocations (including fallback retries)."
          actions={<ExportLink href={exportHref} label="Export CSV" />}>
      <div className="row">
        <div className="field-group">
          <label className="field" htmlFor={winId}>Window</label>
          <select id={winId} value={win} onChange={(e) => setWin(e.target.value)}>
            {WINDOWS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </div>
        <div className="field-group">
          <label className="field" htmlFor={svcId}>Service</label>
          <select id={svcId} value={service} onChange={(e) => setService(e.target.value)}>
            <option value="">All services</option>
            {(services.data?.services || []).map((s: any) => <option key={s.name} value={s.name}>{s.name}</option>)}
          </select>
        </div>
      </div>
      {rows.loading && !rows.data ? <SkeletonTable rows={4} label="Loading Unity Gateway traffic" />
        : rows.error ? <ErrorState error={rows.error} onRetry={rows.reload} title="Couldn't load Unity Gateway traffic" />
        : <Table search label="Unity Gateway traffic" rows={list} columns={cols}
                 empty={<Empty title="No Unity Gateway traffic">Nothing in this window{service ? " for this service" : ""}.</Empty>} />}
    </Card>
  );
}

/* ---------- 6. Enforce (the app never toggles it) ---------- */

function EnforceStep({ scan, enforceTraffic, maxAge }: { scan: any; enforceTraffic: any; maxAge: number }) {
  const age = ageDays(scan?.finished_at);
  const scanOk = !!scan && PASSING.includes(String(scan.readiness)) && (age === null || age <= maxAge);
  const days = scan?.days ?? 30;
  const quiet = enforceTraffic.data ? enforceTraffic.data.total_requests === 0 : null;
  const check = (ok: boolean | null, label: string, detail: ReactNode) => (
    <li>
      {ok === null ? <Badge value="Checking" tone="neutral" /> : ok ? <Badge value="Done" tone="good" /> : <Badge value="Not yet" tone="warn" />}
      <div><b>{label}</b><div className="small muted">{detail}</div></div>
    </li>
  );
  return (
    <Card title="6. Enforce Unity Gateway" note="Enforcing makes databricks-* pay-per-token calls fail with PERMISSION_DENIED. Turn it on only when both checks are done.">
      <ol className="checklist">
        {check(scan ? scanOk : false, "The latest scan passes",
          scan ? `${sentence(String(scan.readiness || "unknown").replace(/_/g, " ").toLowerCase())}, scanned ${relativeAge(scan.finished_at || scan.started_at)}${age !== null && age > maxAge ? ". It's older than the limit: scan again." : "."}` : "No finished scan. Scan the workspace first.")}
        {check(enforceTraffic.error ? false : quiet, `No legacy requests in the last ${days} days`,
          enforceTraffic.error ? "Couldn't check the traffic for the scan's window. Try again." : quiet === null ? "Checking the traffic for the scan's window." : quiet ? "Every legacy endpoint is quiet for the scan's window." : `${fmt(enforceTraffic.data.total_requests)} legacy requests in the window. Move the callers first.`)}
      </ol>
      <Notice tone="info" title="Last step: turn it on in the workspace">
        In the workspace, go to Settings &gt; Advanced &gt; Enforce Unity Gateway and turn it on. This app never changes that setting. <HowToEnforce />
      </Notice>
    </Card>
  );
}

/* ---------- Runs: every verify and cut-over run, newest first ---------- */

function RunHistory({ operator, runs }: { operator: boolean; runs: any }) {
  const [open, setOpen] = useState<string | null>(null);
  const rows: any[] = runs.data || [];
  const runView = useRunView<any>(rows, (r) => r.apply_id === open);
  return (
    <Card title="Verify and cut-over runs" actions={<button className="btn secondary sm" onClick={() => { if (!runs.loading) runs.reload(); }} aria-disabled={runs.loading || undefined}>Reload</button>}>
      {runs.loading && !runs.data ? <SkeletonTable rows={3} label="Loading runs" />
        : runs.error ? <ErrorState error={runs.error} onRetry={runs.reload} />
        : (
          <div className="stack-sm">{runView.controls}
          <Table label="Verify and cut-over runs" rows={runView.shown} pageSize={runView.view === "all" ? 15 : 25} search={runView.view === "all"} rowCurrent={(r) => r.apply_id === open}
                 empty={<Empty title="No runs yet">Test calls, pauses, tracking changes and resumes appear here.</Empty>} columns={[
            { key: "started_at", label: "Started", render: (r) => <button className="btn link" onClick={() => setOpen(r.apply_id)} aria-label={`Open ${OPERATION_LABEL[r.operation] || r.operation} run from ${stamp(r.started_at)}`}>{stamp(r.started_at)}</button> },
            { key: "operation", label: "Step", render: (r) => OPERATION_LABEL[r.operation] || humanize(r.operation) },
            { key: "mode", label: "Mode", render: (r) => <Badge value={r.mode === "rollback" ? "resume" : r.mode} tone={r.mode === "execute" ? "bad" : r.mode === "rollback" ? "warn" : "info"} /> },
            { key: "status", label: "Status", render: (r) => <><Badge value={r.status} />{r.resumed && <div className="small muted">Resumed</div>}</> },
            { key: "targets", label: "Targets", render: (r) => <span className="small">{r.operation === "test_call" ? r.services : r.endpoints}</span> },
            { key: "summary", label: "Result", sortable: false, render: (r) => <span className="small">{summaryLine(r.summary) || "-"}</span> },
            { key: "requested_by", label: "By", hideOnPhone: true },
          ]} />
          </div>
        )}
      {open && <RunDetail applyId={open} onClose={() => setOpen(null)} />}
    </Card>
  );
}

function RunDetail({ applyId, onClose }: { applyId: string; onClose: () => void }) {
  const { data, error, reload } = useApi<any>(`/api/cutover/${applyId}`);
  usePollWhileRunning(data?.meta?.status, error, reload);
  if (isUnknownId(error)) return <Notice tone="warning" title="This run doesn't exist">It may have been removed. <button className="btn link sm" onClick={onClose}>Close</button></Notice>;
  if (error) return <ErrorState error={error} onRetry={reload} title="Couldn't load this run" />;
  if (!data) return <Skeleton lines={3} label="Loading run" />;
  if (data.meta?.status === "RUNNING" || data.meta?.status === "STARTING") {
    return <Notice tone="info">This run is still going. Results appear here when it finishes.</Notice>;
  }
  const m = data.meta;
  return (
    <div className="stack-sm">
      <h3>{OPERATION_LABEL[m.operation] || humanize(m.operation)} run {String(applyId).slice(0, 8)}</h3>
      <p className="small muted">{m.mode === "rollback" ? "Resume" : String(m.mode).replace("_", " ")} by {m.requested_by} · {stamp(m.started_at)} · {relativeAge(m.started_at)}</p>
      <Table label="Run results" rows={data.items} pageSize={50} columns={[
        { key: "name", label: "Target", render: (i) => <code className="wrap">{i.name}</code> },
        { key: "action", label: "Result", render: (i) => <Badge value={ACTION_LABEL[i.action] || humanize(i.action)} tone={ACTION_TONE[i.action] || "neutral"} /> },
        { key: "reason", label: "Details", sortable: false, render: (i) => <span className="small">{i.reason || i.reply_excerpt || i.note || ""}</span> },
      ]} empty={<Empty title="No results">This run didn't check anything.</Empty>} />
      <div className="row"><ExportLink href={`/api/cutover/${applyId}/export`} label="Export results (CSV)" /></div>
    </div>
  );
}
