import { ReactNode, useEffect, useId, useMemo, useRef, useState } from "react";
import { actionLabel, ageDays, api, callerLabel, fmt, humanize, isUnknownId, jobRunning, kindLabel, plural, relativeAge, sentence, useApi, useJob, usePollWhileRunning } from "./api";
import { Badge, Card, CopyButton, Elapsed, Empty, ErrorBox, ErrorState, ExportMenu, HowToEnforce, JobLine, Kpi, Notice, PageHeader, Pager, Reason, Skeleton, SkeletonTable, Table, Tabs, tabPanel } from "./ui";

const STATUS_TEXT: Record<string, string> = {
  READY: "Nothing blocks turning on the Enforce Unity Gateway setting in this workspace.",
  READY_WITH_WARNINGS: "Turning it on won't break anything, but some code still needs to change.",
  INCOMPLETE: "Part of the scan couldn't run, so readiness can't be decided yet.",
  BLOCKED: "Turning it on now would break something. Fix the blockers first.",
};

const NAME_OK = /^[A-Za-z0-9_-]+$/;

export default function Scans({ onApply, operator }: { onApply: (runId: string) => void; operator: boolean }) {
  const list = useApi<any[]>("/api/scans");
  const config = useApi<any>("/api/config");
  const maxAge: number = config.data?.max_scan_age_days ?? 14;
  const host = String(config.data?.workspace_url || "").replace(/^https?:\/\//, "").replace(/\/$/, "");
  const [selected, setSelected] = useState<string | null>(null);
  const [focusNew, setFocusNew] = useState(false);
  const [form, setForm] = useState({ days: 30, scan_roots: "", target_catalog: "ai_gateway", target_schema: "migrated" });
  const [submitted, setSubmitted] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [startErr, setStartErr] = useState<string | null>(null);
  const [conflict, setConflict] = useState<any | null>(null);
  const [conflictJob, setConflictJob] = useState<{ job_run_id: string; url: string | null } | null>(null);
  const [detailKey, setDetailKey] = useState(0);
  const [starting, setStarting] = useState(false);
  const fieldRefs = useRef<Record<string, HTMLInputElement | null>>({});
  const job = useJob(jobId, () => { list.reload(); setDetailKey((k) => k + 1); });
  const activeRow = (list.data || []).find((s) => s.status === "RUNNING");
  const running = jobRunning(jobId, job) || !!activeRow;

  // A scan that is still running (started before a reload, or by someone else) resumes its progress view.
  useEffect(() => {
    if (!jobId && activeRow) {
      setJobId(activeRow.job_run_id);
      setSelected(activeRow.run_id);
    }
  }, [list.data]);

  // One message per field, shown next to the field. The summary (after a submit) only links to them.
  const errors = [
    !(form.days >= 1 && form.days <= 365) && { id: "scan-days", label: "Traffic window", text: "Use a number of days from 1 to 365." },
    !NAME_OK.test(form.target_catalog) && { id: "scan-catalog", label: "Target catalog", text: "Use letters, digits, _ and -." },
    !NAME_OK.test(form.target_schema) && { id: "scan-schema", label: "Target schema", text: "Use letters, digits, _ and -." },
  ].filter(Boolean) as { id: string; label: string; text: string }[];
  const errorFor = (id: string) => errors.find((e) => e.id === id)?.text;
  const focusField = (id: string) => fieldRefs.current[id]?.focus();
  const reasons = [!operator && "Only operators can start a scan.", running && "A scan is already running."].filter(Boolean) as string[];
  const startDisabled = reasons.length > 0 || starting;
  const describe = (id: string) => (errorFor(id) ? `${id}-error` : undefined);

  const start = async () => {
    if (startDisabled) return;
    setSubmitted(true);
    if (errors.length) { focusField(errors[0].id); return; }
    setStartErr(null);
    setConflict(null);
    setConflictJob(null);
    setStarting(true);
    try {
      const r = await api("/api/scans", { method: "POST", body: JSON.stringify(form) });
      setJobId(r.job_run_id);
      setSelected(r.run_id);
      setFocusNew(true);
      setSubmitted(false);
    } catch (e: any) {
      setStartErr(e.message);
      if (e.status === 409) {
        setConflictJob(e.job ?? null);
        setConflict(await api<any[]>("/api/scans").then((rows) => rows.find((s) => s.status === "RUNNING") || null).catch(() => null));
      }
    } finally {
      setStarting(false);
    }
  };
  const showRunning = (row: any) => {
    setJobId(row.job_run_id);
    setSelected(row.run_id);
    setFocusNew(true);
    setConflict(null);
    setConflictJob(null);
    setStartErr(null);
  };

  return (
    <div className="stack">
      <PageHeader title="Workspace scans"
                  description={<>Scans cover this workspace only{host ? <> (<code>{host}</code>)</> : null}. A scan reads its endpoints, callers and code, and saves the results. It takes a few minutes.</>} />
      <Card title="Start a scan">
        <form className="form" noValidate onSubmit={(e) => { e.preventDefault(); start(); }}>
          <div className="field-group">
            <label className="field" htmlFor="scan-days">Traffic window (days)</label>
            <input id="scan-days" type="number" min={1} max={365} required ref={(el) => { fieldRefs.current["scan-days"] = el; }}
                   aria-invalid={!!errorFor("scan-days")} aria-describedby={describe("scan-days")}
                   value={Number.isNaN(form.days) ? "" : form.days} onChange={(e) => setForm({ ...form, days: e.target.valueAsNumber })} />
            {errorFor("scan-days") && <span id="scan-days-error" className="field-error">{errorFor("scan-days")}</span>}
          </div>
          <div className="field-group">
            <label className="field" htmlFor="scan-roots">Scan folders (optional)</label>
            <input id="scan-roots" placeholder="/Shared/team, /Repos/app" aria-describedby="scan-roots-hint"
                   value={form.scan_roots} onChange={(e) => setForm({ ...form, scan_roots: e.target.value })} />
            <span id="scan-roots-hint" className="small muted">Leave blank to scan /Users, /Shared and /Repos; folders you enter replace that list.</span>
          </div>
          <details className="advanced" open={!NAME_OK.test(form.target_catalog) || !NAME_OK.test(form.target_schema) || undefined}>
            <summary>Advanced: target schema for the proposed names</summary>
            <p className="small muted">Optional. You choose the target in Apply and can change it there without scanning again. This only sets the service names the scan reports (default <code>ai_gateway.migrated</code>).</p>
          <div className="field-group">
            <label className="field" htmlFor="scan-catalog">Target catalog (Unity Catalog)</label>
            <input id="scan-catalog" required ref={(el) => { fieldRefs.current["scan-catalog"] = el; }}
                   aria-invalid={!NAME_OK.test(form.target_catalog)} aria-describedby={describe("scan-catalog")}
                   value={form.target_catalog} onChange={(e) => setForm({ ...form, target_catalog: e.target.value })} />
            {errorFor("scan-catalog") && <span id="scan-catalog-error" className="field-error">{errorFor("scan-catalog")}</span>}
          </div>
          <div className="field-group">
            <label className="field" htmlFor="scan-schema">Target schema (Unity Catalog)</label>
            <input id="scan-schema" required ref={(el) => { fieldRefs.current["scan-schema"] = el; }}
                   aria-invalid={!NAME_OK.test(form.target_schema)} aria-describedby={describe("scan-schema")}
                   value={form.target_schema} onChange={(e) => setForm({ ...form, target_schema: e.target.value })} />
            {errorFor("scan-schema") && <span id="scan-schema-error" className="field-error">{errorFor("scan-schema")}</span>}
          </div>
          </details>
          <button type="submit" className="btn" aria-disabled={startDisabled || undefined}
                  aria-describedby={reasons.length ? "scan-start-reason" : undefined}>
            {starting || running ? "Scanning…" : "Start scan"}
          </button>
        </form>
        {submitted && errors.length > 0 && (
          <Notice tone="error" title="Fix these to start the scan">
            <ul className="small">
              {errors.map((e) => (
                <li key={e.id}>
                  <a href={`#${e.id}`} onClick={(ev) => { ev.preventDefault(); focusField(e.id); }}>{e.label}: {e.text}</a>
                </li>
              ))}
            </ul>
          </Notice>
        )}
        <p className="muted small">You choose the target schema for new services in Apply, and can change it there without scanning again.</p>
        {reasons.length > 0 && <Reason id="scan-start-reason">Start scan is unavailable: {reasons.join(" ")}</Reason>}
        {jobId && <JobLine state={job} label="Scan" done="Results are below." />}
        {startErr && <ErrorBox error={startErr} title="Couldn't start the scan" />}
        {(conflict || conflictJob) && (
          <Notice tone="info" action={<>
            {conflict && <button className="btn secondary sm" onClick={() => showRunning(conflict)}>Show the running scan</button>}
            {conflictJob?.url && <a className="btn link sm" href={conflictJob.url} target="_blank" rel="noreferrer">View job run</a>}
          </>}>
            {conflict ? `Another scan is already running, started ${relativeAge(conflict.started_at)} by ${conflict.requested_by}.` : "Another scan is already running."}
          </Notice>
        )}
      </Card>
      <Card title="Scan history" actions={<button className="btn secondary sm" onClick={() => { if (!list.loading) list.reload(); }} aria-disabled={list.loading || undefined}>Reload</button>}>
        {list.loading && !list.data ? <SkeletonTable rows={4} label="Loading scan history" /> : list.error ? <ErrorState error={list.error} onRetry={list.reload} /> : (
          <Table label="Scan history" rows={list.data || []} rowCurrent={(r) => r.run_id === selected}
                 empty={<Empty title="No scans yet">Start a scan above to see readiness, callers and code fixes.</Empty>} columns={[
            { key: "started_at", label: "Started", render: (r) => <button className="btn link" onClick={() => { setSelected(r.run_id); setFocusNew(true); }} aria-label={`Open scan started ${String(r.started_at).slice(0, 16)}`}>{String(r.started_at).slice(0, 16)}</button> },
            { key: "workspace_url", label: "Workspace", render: (r) => <span className="small">{r.workspace_url?.replace("https://", "") || "-"}</span> },
            { key: "status", label: "Status", render: (r) => <><Badge value={r.status} />{r.error && r.status === "FAILED" && <div className="small text-bad">{String(r.error).slice(0, 120)}</div>}</> },
            { key: "readiness", label: "Readiness", render: (r) => r.readiness ? <Badge value={r.readiness} /> : "-" },
            { key: "endpoints", label: "Endpoints", num: true, render: (r) => fmt(r.endpoints) },
            { key: "client_references", label: "Code refs", num: true, render: (r) => fmt(r.client_references) },
            { key: "requested_by", label: "By" },
          ]} />
        )}
      </Card>
      {selected && (
        <ScanDetail key={`${selected}-${detailKey}`} runId={selected} onApply={onApply} focus={focusNew} maxAge={maxAge}
                    onClose={() => setSelected(null)} />
      )}
    </div>
  );
}

function scanAgain() {
  const el = document.getElementById("scan-days");
  el?.scrollIntoView({ block: "center" });
  el?.focus();
}

function ScanDetail({ runId, onApply, focus, maxAge, onClose }: {
  runId: string; onApply: (runId: string) => void; focus: boolean; maxAge: number; onClose: () => void;
}) {
  const { data, error, loading, reload } = useApi<any>(`/api/scans/${runId}`);
  const [tab, setTab] = useState("readiness");
  const heading = useRef<HTMLHeadingElement>(null);
  // Move focus to the new run's heading once, so keyboard and screen reader users land on the progress view.
  useEffect(() => { if (focus) heading.current?.focus(); }, []);
  usePollWhileRunning(data?.meta?.status, error, reload);
  if (isUnknownId(error)) {
    return (
      <Card title="Scan not found" headingRef={heading}>
        <Notice tone="warning" title="This scan doesn't exist">It may have been removed, or the link is out of date.</Notice>
        <div className="row"><button className="btn secondary sm" onClick={onClose}>Back to scan history</button></div>
      </Card>
    );
  }
  const inProgress = !!data && (data.meta?.status === "RUNNING" || data.meta?.status === "STARTING");
  if (inProgress) {
    return (
      <Card title="Scan in progress" headingRef={heading} note={data?.meta?.started_at ? <>Started {String(data.meta.started_at).slice(0, 16)} UTC by {data.meta.requested_by} · <Elapsed since={data.meta.started_at} /></> : undefined}>
        <Notice tone="info">{data?.meta?.status === "STARTING" ? "Starting the scan. This page checks automatically." : "The scan is running. Results appear here when it finishes; this page checks automatically."}</Notice>
        <Skeleton lines={4} label="Waiting for scan results" />
      </Card>
    );
  }
  if (loading && !data) return <Card title="Loading scan" headingRef={heading}><Skeleton lines={4} label="Loading scan" /></Card>;
  if (error) return <Card title="Scan" headingRef={heading}><ErrorState error={error} onRetry={reload} title="Couldn't load this scan" /></Card>;
  const m = data.meta, r = data.readiness || {};
  if (m.status !== "SUCCEEDED") {
    return (
      <Card title="Scan" headingRef={heading} actions={<button className="btn secondary sm" onClick={reload}>Reload</button>}>
        <Notice tone="error" title={`Scan ${String(m.status).toLowerCase()}`}>{m.error || "The scan didn't finish. Check the job run, fix the cause and start a new scan."}</Notice>
        <p className="muted small">Started {String(m.started_at).slice(0, 16)} UTC by {m.requested_by}</p>
      </Card>
    );
  }
  const base = `/api/scans/${runId}/export`;
  const age = ageDays(m.finished_at);
  const tabs = [["readiness", "Readiness"], ["endpoints", `Endpoints (${data.plan.length})`], ["callers", `Callers (${data.callers.length})`],
    ["code", count("Code fixes", data.ref_counts?.fixes)], ["refs", count("All references", data.ref_counts?.all)]] as const;
  return (
    <Card title={`Scan of ${m.workspace_url?.replace("https://", "")}`} headingRef={heading}
          note={`Finished ${String(m.finished_at).slice(0, 16)} UTC (${relativeAge(m.finished_at)}) · ${m.days}-day window · by ${m.requested_by}`}
          actions={<>
            <ExportMenu items={[
              { href: `${base}/readiness`, label: "Readiness report", hint: "Markdown" },
              { href: `${base}/code-fixes`, label: "Code fixes", hint: "Markdown" },
              { href: `${base}/summary`, label: "Summary", hint: "Markdown" },
              { href: `${base}/plan`, label: "Endpoint plan", hint: "CSV" },
              { href: `${base}/callers`, label: "Callers", hint: "CSV" },
              { href: `${base}/references`, label: "All references", hint: "CSV" },
              { href: `${base}/providers`, label: "Provider services", hint: "CSV" },
            ]} />
            <button className="btn sm" onClick={() => onApply(runId)}>Open in Apply</button>
          </>}>
      <div className={`banner ${r.status === "READY" ? "good" : r.status === "BLOCKED" ? "bad" : "warn"}`}>
        <Badge value={r.status} /> <span>{STATUS_TEXT[r.status] || ""}</span>
      </div>
      {age !== null && age > maxAge && (
        <Notice tone="warning" title={`This scan is ${relativeAge(m.finished_at)} old`}
                action={<button className="btn secondary sm" onClick={scanAgain}>Scan again</button>}>
          The limit is {plural(maxAge, "day")}. Endpoints and callers may have changed since: scan again before you apply or enforce.
        </Notice>
      )}
      <Tabs label="Scan results" panelId="scan-results" tabs={tabs} value={tab} onChange={setTab} />
      <div {...tabPanel("scan-results", tab)}>
        {tab === "readiness" && <Readiness r={r} callers={data.callers.length} fixes={data.ref_counts?.fixes || 0} onTab={setTab} />}
        {tab === "endpoints" && <Endpoints plan={data.plan} providers={data.providers} />}
        {tab === "callers" && (
          <Table search label="Callers of legacy endpoints" rows={data.callers} empty="No legacy traffic in the window" columns={[
            { key: "endpoint_name", label: "Endpoint", render: (c) => <code>{c.endpoint_name}</code> },
            { key: "requester_name", label: "Caller" },
            { key: "caller_class", label: "Caller type", render: (c) => <span className="small">{callerLabel(c.caller_class)}</span> },
            { key: "user_agent", label: "User agent", hideOnPhone: true, render: (c) => c.user_agent
              ? <code className="small wrap">{String(c.user_agent).slice(0, 80)}</code> : <span className="muted small">-</span> },
            { key: "requests", label: "Requests", num: true, render: (c) => fmt(c.requests) },
            { key: "last_request", label: "Last request", render: (c) => String(c.last_request || "").slice(0, 16) },
            { key: "linked_code", label: "Code found", render: (c) => (c.linked_code || []).length ? (c.linked_code || []).slice(0, 3).map((x: string) => <div key={x} className="small"><code>{x}</code></div>) : <span className="muted small">Not in this caller's folders: check jobs, external apps and Git repos</span> },
          ]} />
        )}
        {tab === "code" && <CodeFixes runId={runId} />}
        {tab === "refs" && <AllRefs runId={runId} />}
      </div>
    </Card>
  );
}

const count = (label: string, n: any) => (n === undefined || n === null ? label : `${label} (${fmt(n)})`);

/** What to do about a coverage gap, from what the scan reported. */
const gapFix = (what: string) =>
  /permission|denied|access|forbidden/i.test(what) ? "Give the scan's identity read access to it, then scan again."
    : /skipped|size|limit|too (large|many)/i.test(what) ? "Narrow the scan folders (optional field above), then scan again."
    : "Fix the cause above, then scan again.";

function Readiness({ r, callers, fixes, onTab }: { r: any; callers: number; fixes: number; onTab: (k: string) => void }) {
  const gaps = Object.entries(r.coverage_gaps || {}) as [string, string][];
  const blockers: any[] = r.blockers || [];
  const warnings: any[] = r.warnings || [];
  // Warnings grouped by their plain label, so each kind shows once with a count.
  const warnGroups = useMemo(() => {
    const g = new Map<string, { label: string; n: number; action: string }>();
    for (const w of warnings) {
      const label = w.label || humanize(w.type);
      const cur = g.get(label) || { label, n: 0, action: "" };
      cur.n += 1;
      if (!cur.action && w.action) cur.action = w.action;
      g.set(label, cur);
    }
    return [...g.values()];
  }, [r]);
  const candidates = r.rate_limit_zero_candidates || [];
  // The next step depends on the status: each one says what to do next, in order.
  const nextStep: Record<string, ReactNode> = {
    READY: <>Nothing blocks enforcing. Move the remaining callers, scan again to confirm, then turn on the Enforce Unity Gateway setting in the workspace admin settings. <HowToEnforce /></>,
    READY_WITH_WARNINGS: <>No blockers. Review each warning before you enforce. Fix the code in the source (and its Git repo), move the callers, then scan again. <HowToEnforce /></>,
    BLOCKED: <>Fix the {plural(blockers.length, "blocker")} below first. Until then, turning on the Enforce Unity Gateway setting breaks them. <HowToEnforce /></>,
    INCOMPLETE: <>This scan couldn't read everything, so readiness isn't decided yet. Fix the coverage gaps below, then scan again.</>,
  };
  return (
    <div className="stack">
      <div className="kpis">
        <Kpi label="Blockers" value={blockers.length} tone={blockers.length ? "bad" : "good"} />
        <Kpi label="Warnings" value={warnings.length} tone={warnings.length ? "warn" : "good"} />
        <Kpi label="Coverage gaps" value={gaps.length} tone={gaps.length ? "warn" : "good"} sub={r.traffic_status && r.traffic_status !== "ok" ? "traffic not confirmed" : "traffic confirmed"} />
        <Kpi label="Can be closed now" value={candidates.length} sub="external model endpoints" />
      </div>
      <div className="next-line small">
        <b>Next:</b> <span>{nextStep[r.status] ?? "Check the blockers and warnings below, then scan again."}</span>
        <span className="row">
          {fixes > 0 && <button className="btn secondary sm" onClick={() => onTab("code")}>Code fixes ({fmt(fixes)})</button>}
          {callers > 0 && <button className="btn secondary sm" onClick={() => onTab("callers")}>Callers ({fmt(callers)})</button>}
        </span>
      </div>
      {gaps.length > 0 && (
        <Card title="Coverage gaps" note="What the scan couldn't read, and the fix.">
          <Table label="Coverage gaps" rows={gaps.map(([k, v]) => ({ surface: humanize(k), status: v, fix: gapFix(v) }))} columns={[
            { key: "surface", label: "Surface" },
            { key: "status", label: "What happened", render: (g) => <span className="small">{g.status}</span> },
            { key: "fix", label: "Fix", render: (g) => <span className="small">{g.fix}</span> },
          ]} />
        </Card>
      )}
      <Card title="Blockers" note={<>These break when the Enforce Unity Gateway setting is on. <HowToEnforce /></>}>
        <Table label="Blockers" rows={blockers} empty={<Empty title="No blockers" />} columns={[
          { key: "label", label: "Blocker", render: (b) => <Badge value={b.label || humanize(b.type)} tone="bad" /> },
          { key: "item", label: "Item", render: (b) => <code>{b.item}</code> },
          { key: "action", label: "What to do", render: (b) => (
            <><span className="small">{sentence(b.action || b.detail)}</span>{b.action && b.detail && <div className="small muted">{b.detail}</div>}</>) },
        ]} />
      </Card>
      <Card title="Warnings" note="Won't block enforcing, but each one needs a look before callers move.">
        <Table label="Warnings" rows={warnGroups} empty={<Empty title="No warnings" />} columns={[
          { key: "label", label: "Warning" },
          { key: "n", label: "Count", num: true },
          { key: "action", label: "What to do", render: (w) => <span className="small">{w.action ? sentence(w.action) : "-"}</span> },
        ]} />
      </Card>
      <Card title="Can be closed now" note="External model endpoints with no traffic, dependents or references.">
        {candidates.length === 0 ? <Empty title="Nothing to close">No external model endpoint in this workspace is idle, with no dependents or references.</Empty> : (
          <>
            <Notice tone="warning">These commands change the legacy endpoint; the app never runs them. Close sets its rate limit to 0 (undo restores the current settings). Confirm with the owner, then run them with the Databricks CLI.</Notice>
            <div>
              {candidates.map((c: any) => {
                const path = `/api/2.0/serving-endpoints/${c.endpoint}/ai-gateway`;
                const close = `databricks api put '${path}' --json '${JSON.stringify(c.ai_gateway_body).replace(/'/g, "'\\''")}'`;
                const undo = `databricks api put '${path}' --json '${JSON.stringify(c.undo_body).replace(/'/g, "'\\''")}'`;
                return (
                  <div key={c.endpoint} className="candidate">
                    <code>{c.endpoint}</code> {c.target_ready ? <Badge value="target exists" tone="good" /> : <Badge value="run apply first" tone="warn" />}
                    <CopyButton text={close} label="Copy close command" /> <CopyButton text={undo} label="Copy undo command" />
                  </div>
                );
              })}
            </div>
          </>
        )}
      </Card>
    </div>
  );
}

function Endpoints({ plan, providers }: { plan: any[]; providers: any[] }) {
  const [action, setAction] = useState("");
  const rows = action ? plan.filter((p) => p.action === action) : plan;
  const actions = Array.from(new Set(plan.map((p) => p.action)));
  return (
    <div className="stack">
      <div className="row" role="group" aria-label="Filter by plan">
        <button className="btn secondary sm" aria-pressed={!action} onClick={() => setAction("")}>All</button>
        {actions.map((a) => <button key={a} className="btn secondary sm" aria-pressed={action === a} onClick={() => setAction(a)}>{actionLabel(a)}</button>)}
      </div>
      <Table search label="Endpoint plan" rows={rows} empty="No legacy endpoints in this workspace" columns={[
        { key: "legacy_endpoint", label: "Legacy endpoint", render: (p) => <code>{p.legacy_endpoint}</code> },
        { key: "kind", label: "Kind", render: (p) => <>{kindLabel(p.kind)}{p.kind === "v2_workspace_endpoint" && <> <Badge value="v2" tone="warn" /></>}</> },
        { key: "action", label: "Plan", render: (p) => <Badge value={actionLabel(p.action)} tone={p.action === "create_model_service" ? "info" : p.action === "use_system_ai" ? "good" : "neutral"} /> },
        { key: "target_service", label: "Target", render: (p) => p.target_service ? <><code>{p.target_service}</code> {p.target_status === "exists" && <Badge value="exists" tone="good" />}</> : "-" },
        { key: "requests_window", label: "Requests", num: true, render: (p) => fmt(p.requests_window) },
        { key: "tokens_window", label: "Tokens", num: true, hideOnPhone: true, render: (p) => fmt(p.tokens_window) },
        { key: "needs_human", label: "Needs a person", sortable: false, render: (p) => (Array.isArray(p.needs_human) ? p.needs_human : []).map((n: string, i: number) => <div key={i} className="small">{n}</div>) },
      ]} />
      {providers.length > 0 && (
        <Card title="Provider services the plan needs">
          <Table label="Provider services" rows={providers} columns={[
            { key: "provider_service", label: "Provider service", render: (p) => <code>{p.provider_service}</code> },
            { key: "provider", label: "Provider" },
            { key: "models", label: "Models", render: (p) => (Array.isArray(p.models) ? p.models : []).join(", ") },
            { key: "secrets", label: "Secrets", render: (p) => (Array.isArray(p.secrets) ? p.secrets : []).join(", ") || "-" },
          ]} />
        </Card>
      )}
    </div>
  );
}

/** One server-side page of a scan's references; the filter runs in SQL, so large scans stay fast. */
function usePagedRefs(runId: string, kind: "all" | "fixes", pageSize: number) {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  useEffect(() => { const t = setTimeout(() => { setQuery(q); setPage(0); }, 400); return () => clearTimeout(t); }, [q]);
  const res = useApi<any>(`/api/scans/${runId}/refs?kind=${kind}&q=${encodeURIComponent(query)}&offset=${page * pageSize}&limit=${pageSize}`);
  const total = Number(res.data?.total || 0);
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const pager = pages > 1 && <Pager page={page} pages={pages} total={total} onPage={setPage} busy={res.loading} />;
  return { ...res, rows: (res.data?.rows || []) as any[], total, q, setQ, pager };
}

function FilterInput({ value, onChange, label, updating }: { value: string; onChange: (v: string) => void; label: string; updating?: boolean }) {
  const id = useId();
  return (
    <div className="table-tools">
      <div className="filter">
        <label htmlFor={id} className="filter-label">{label}</label>
        <input id={id} type="search" className="search" value={value} onChange={(e) => onChange(e.target.value)} />
      </div>
      {updating && <span className="muted small" aria-hidden="true">Updating…</span>}
    </div>
  );
}

function AllRefs({ runId }: { runId: string }) {
  const r = usePagedRefs(runId, "all", 100);
  return (
    <div>
      <FilterInput label="Filter by path, endpoint or pattern" value={r.q} onChange={r.setQ} updating={!!r.loading && !!r.data} />
      {r.error ? <ErrorState error={r.error} onRetry={r.reload} /> : r.loading && !r.data ? <SkeletonTable label="Loading references" /> : (
        <Table label="Client references" rows={r.rows} pageSize={100} empty={r.q ? <Empty title="No matches" /> : <Empty title="No references found" />} columns={[
          { key: "asset_type", label: "Type" },
          { key: "asset", label: "Where", render: (x) => <><code className="wrap">{x.asset}</code>{x.line ? <span className="muted small">:{x.line}</span> : null}</> },
          { key: "pattern", label: "Pattern" },
          { key: "legacy_endpoint", label: "Endpoint", render: (x) => x.legacy_endpoint ? <code>{x.legacy_endpoint}</code> : "-" },
          { key: "suggestion", label: "Suggestion", sortable: false, render: (x) => <span className="small">{x.suggestion}</span> },
        ]} />
      )}
      {r.pager}
    </div>
  );
}

/** Proposed code fixes, grouped by file. Lines load in server order (by file) and accumulate, so a file's group
 *  is never split across pages; "Show more" extends the list up to 1,000 lines, then the filter narrows it. */
function CodeFixes({ runId }: { runId: string }) {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(200);
  useEffect(() => { const t = setTimeout(() => { setQuery(q); setLimit(200); }, 400); return () => clearTimeout(t); }, [q]);
  const res = useApi<any>(`/api/scans/${runId}/refs?kind=fixes&q=${encodeURIComponent(query)}&offset=0&limit=${limit}`);
  const rows: any[] = res.data?.rows || [];
  const total = Number(res.data?.total || 0);
  const groups = useMemo(() => {
    const g: Record<string, any[]> = {};
    rows.forEach((x) => (g[x.asset] = g[x.asset] || []).push(x));
    return Object.entries(g);
  }, [res.data]);
  if (res.error) return <ErrorState error={res.error} onRetry={res.reload} />;
  if (res.loading && !res.data) return <SkeletonTable label="Loading code fixes" />;
  if (total === 0 && !query) return <Empty title="No code changes needed">No references in this workspace need a rewrite.</Empty>;
  const more = rows.length < total;
  const atCap = limit >= 1000;
  return (
    <div className="stack">
      <p className="muted small"><Badge value="review" tone="warn" /> check each change before applying it. Edit the source (and its Git repo), then scan again. Lines with a credential get no proposed fix.</p>
      <FilterInput label="Filter by path" value={q} onChange={setQ} updating={!!res.loading && !!res.data} />
      {groups.length === 0 && <Empty title="No matches" />}
      {groups.map(([asset, items]) => (
        <details key={asset} className="diff" open={groups.length <= 10}>
          <summary><code className="wrap">{asset}</code> <span className="muted small">{plural(items.length, "line")}</span></summary>
          {items.map((x, i) => (
            <div key={i} className="diff-item">
              <div className="row small muted">Line {x.line} <Badge value={x.fix_confidence} tone={x.fix_confidence === "auto" ? "good" : "warn"} /> <CopyButton text={x.fixed_line} label="Copy new line" /></div>
              <pre className="del"><span className="sr-only">Old: </span>- {x.line_text}</pre>
              <pre className="add"><span className="sr-only">New: </span>+ {x.fixed_line}</pre>
            </div>
          ))}
        </details>
      ))}
      {more && (
        <div className="row">
          <span className="small muted">Showing {fmt(rows.length)} of {fmt(total)} lines.{atCap ? " Filter by path to see more." : " The last file may continue below."}</span>
          {!atCap && (
            <button className="btn secondary sm" aria-disabled={res.loading || undefined}
                    onClick={() => { if (!res.loading) setLimit(Math.min(1000, limit + 200)); }}>Show more</button>
          )}
        </div>
      )}
    </div>
  );
}
