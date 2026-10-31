import { useEffect, useMemo, useRef, useState } from "react";
import { ageDays, api, fmt, jobRunning, relativeAge, useApi, useJob, usePollWhileRunning } from "./api";
import { Badge, Card, CopyButton, Elapsed, Empty, ErrorBox, ErrorState, ExportMenu, JobLine, Kpi, Notice, PageHeader, Pager, Reason, Skeleton, SkeletonTable, Table, Tabs, tabPanel } from "./ui";

const STATUS_TEXT: Record<string, string> = {
  READY: "Nothing blocks Enforce Unity Gateway in this workspace.",
  READY_WITH_WARNINGS: "Enforcing won't break anything, but some code still needs to change.",
  INCOMPLETE: "Part of the scan failed or traffic couldn't be confirmed, so readiness can't be decided yet.",
  BLOCKED: "Enforcing now would break something. Fix the blockers first.",
};

const NAME_OK = /^[A-Za-z0-9_-]+$/;
/** Scans older than this are stale: the plan may no longer match the workspace. Matches UGMIG_MAX_SCAN_AGE_DAYS by default. */
const STALE_DAYS = 14;

export default function Scans({ onApply, operator }: { onApply: (runId: string) => void; operator: boolean }) {
  const list = useApi<any[]>("/api/scans");
  const [selected, setSelected] = useState<string | null>(null);
  const [focusNew, setFocusNew] = useState(false);
  const [form, setForm] = useState({ days: 30, scan_roots: "", target_catalog: "ai_gateway", target_schema: "migrated" });
  const [submitted, setSubmitted] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [startErr, setStartErr] = useState<string | null>(null);
  const [conflict, setConflict] = useState<any | null>(null);
  const [detailKey, setDetailKey] = useState(0);
  const [starting, setStarting] = useState(false);
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

  const errors = [
    !(form.days >= 1 && form.days <= 365) && { id: "scan-days", text: "Traffic window: use a number of days from 1 to 365." },
    !NAME_OK.test(form.target_catalog) && { id: "scan-catalog", text: "Target catalog: use letters, digits, _ and -." },
    !NAME_OK.test(form.target_schema) && { id: "scan-schema", text: "Target schema: use letters, digits, _ and -." },
  ].filter(Boolean) as { id: string; text: string }[];
  const reasons = [!operator && "View only: ask an operator to start scans.", activeRow && "A scan is already running."].filter(Boolean) as string[];

  const start = async () => {
    if (errors.length) { setSubmitted(true); return; }
    setStartErr(null);
    setConflict(null);
    setStarting(true);
    try {
      const r = await api("/api/scans", { method: "POST", body: JSON.stringify(form) });
      setJobId(r.job_run_id);
      setSelected(r.run_id);
      setFocusNew(true);
    } catch (e: any) {
      setStartErr(e.message);
      if (e.status === 409) setConflict(await api<any[]>("/api/scans").then((rows) => rows.find((s) => s.status === "RUNNING") || null).catch(() => null));
    } finally {
      setStarting(false);
    }
  };
  const showRunning = (row: any) => {
    setJobId(row.job_run_id);
    setSelected(row.run_id);
    setFocusNew(true);
    setConflict(null);
    setStartErr(null);
  };

  return (
    <div className="stack">
      <PageHeader title="Workspace scans" description="A scan reads this workspace (endpoints, traffic and code) and saves the results. It takes a few minutes." />
      <Card title="Start a scan">
        <form className="form" noValidate onSubmit={(e) => { e.preventDefault(); start(); }}>
          <label className="field">Traffic window (days)
            <input type="number" min={1} max={365} required aria-invalid={!(form.days >= 1 && form.days <= 365)}
                   aria-describedby={!(form.days >= 1 && form.days <= 365) ? "scan-days" : undefined}
                   value={Number.isNaN(form.days) ? "" : form.days} onChange={(e) => setForm({ ...form, days: e.target.valueAsNumber })} />
          </label>
          <label className="field">Scan folders (optional)
            <input placeholder="/Shared/team, /Repos/app" value={form.scan_roots} onChange={(e) => setForm({ ...form, scan_roots: e.target.value })} />
          </label>
          <label className="field">Target catalog (Unity Catalog)
            <input required aria-invalid={!NAME_OK.test(form.target_catalog)} aria-describedby={!NAME_OK.test(form.target_catalog) ? "scan-catalog" : undefined}
                   value={form.target_catalog} onChange={(e) => setForm({ ...form, target_catalog: e.target.value })} />
          </label>
          <label className="field">Target schema (Unity Catalog)
            <input required aria-invalid={!NAME_OK.test(form.target_schema)} aria-describedby={!NAME_OK.test(form.target_schema) ? "scan-schema" : undefined}
                   value={form.target_schema} onChange={(e) => setForm({ ...form, target_schema: e.target.value })} />
          </label>
          <button type="submit" className="btn" disabled={!operator || starting || running} aria-describedby={reasons.length ? "scan-start-reason" : undefined}>
            {starting || running ? "Scanning…" : "Start scan"}
          </button>
        </form>
        {submitted && errors.length > 0 && (
          <div role="alert" className="notice error">
            <span className="notice-icon" aria-hidden="true">!</span>
            <div className="notice-body">
              <strong>Fix these to start the scan</strong>
              <ul className="small">{errors.map((e) => <li key={e.id}><a href={`#${e.id}`}>{e.text}</a></li>)}</ul>
            </div>
          </div>
        )}
        {errors.map((e) => <p key={e.id} id={e.id} className="small text-bad">{e.text}</p>)}
        <p className="muted small">Blank scans /Users, /Shared and /Repos; folders you enter replace that list. The target is where apply would create model services; create that schema before you apply.</p>
        {reasons.length > 0 && <Reason id="scan-start-reason">Start scan is unavailable: {reasons.join(" ")}</Reason>}
        {jobId && <JobLine state={job} label="Scan" done="Results are below." />}
        {startErr && <ErrorBox error={startErr} />}
        {conflict && (
          <Notice tone="info" action={<button className="btn secondary sm" onClick={() => showRunning(conflict)}>Show the running scan</button>}>
            Another scan is already running, started {relativeAge(conflict.started_at)} by {conflict.requested_by}.
          </Notice>
        )}
      </Card>
      <Card title="Scan history" actions={<button className="btn secondary sm" onClick={list.reload} disabled={list.loading}>Reload</button>}>
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
      {selected && <ScanDetail key={`${selected}-${detailKey}`} runId={selected} onApply={onApply} focus={focusNew} />}
    </div>
  );
}

function ScanDetail({ runId, onApply, focus }: { runId: string; onApply: (runId: string) => void; focus: boolean }) {
  const { data, error, loading, reload } = useApi<any>(`/api/scans/${runId}`);
  const [tab, setTab] = useState("readiness");
  const heading = useRef<HTMLHeadingElement>(null);
  // Move focus to the new run's heading once, so keyboard and screen reader users land on the progress view.
  useEffect(() => { if (focus) heading.current?.focus(); }, []);
  usePollWhileRunning(data?.meta?.status, error, reload);
  const inProgress = error?.startsWith("404") || (!!data && data.meta?.status === "RUNNING");
  if (inProgress) {
    return (
      <Card title="Scan in progress" headingRef={heading} note={data?.meta?.started_at ? <>Started {String(data.meta.started_at).slice(0, 16)} UTC by {data.meta.requested_by} · <Elapsed since={data.meta.started_at} /></> : undefined}>
        <Notice tone="info">The scan is running. Results appear here when it finishes; this page checks automatically.</Notice>
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
            <button className="btn sm" onClick={() => onApply(runId)}>Plan apply</button>
          </>}>
      <div className={`banner ${r.status === "READY" ? "good" : r.status === "BLOCKED" ? "bad" : "warn"}`}>
        <Badge value={r.status} /> <span>{STATUS_TEXT[r.status] || ""}</span>
      </div>
      {age !== null && age > STALE_DAYS && <Notice tone="warning">This scan is {relativeAge(m.finished_at)}. Callers and endpoints may have changed since: scan again before you apply or enforce.</Notice>}
      <Tabs label="Scan results" panelId="scan-results" tabs={tabs} value={tab} onChange={setTab} />
      <div {...tabPanel("scan-results", tab)}>
        {tab === "readiness" && <Readiness r={r} callers={data.callers.length} fixes={data.ref_counts?.fixes || 0} onTab={setTab} />}
        {tab === "endpoints" && <Endpoints plan={data.plan} providers={data.providers} />}
        {tab === "callers" && (
          <Table search label="Callers of legacy endpoints" rows={data.callers} empty="No legacy traffic in the window" columns={[
            { key: "endpoint_name", label: "Endpoint", render: (c) => <code>{c.endpoint_name}</code> },
            { key: "requester_name", label: "Caller" },
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

function Readiness({ r, callers, fixes, onTab }: { r: any; callers: number; fixes: number; onTab: (k: string) => void }) {
  const gaps = Object.entries(r.coverage_gaps || {});
  const warnCounts = useMemo(() => {
    const c: Record<string, number> = {};
    (r.warnings || []).forEach((w: any) => (c[w.type] = (c[w.type] || 0) + 1));
    return Object.entries(c).map(([type, n]) => ({ type, n }));
  }, [r]);
  const candidates = r.rate_limit_zero_candidates || [];
  const blockers = (r.blockers || []).length;
  return (
    <div className="stack">
      <div className="kpis">
        <Kpi label="Blockers" value={blockers} tone={blockers ? "bad" : "good"} />
        <Kpi label="Warnings" value={(r.warnings || []).length} tone={(r.warnings || []).length ? "warn" : "good"} />
        <Kpi label="Scan gaps" value={gaps.length} tone={gaps.length ? "warn" : "good"} sub={r.traffic_status && r.traffic_status !== "ok" ? "traffic not confirmed" : "traffic confirmed"} />
        <Kpi label="Can be closed now" value={candidates.length} sub="external model endpoints" />
      </div>
      <div className="next-line small">
        <b>Next:</b> {blockers ? `fix the ${blockers} blocker${blockers === 1 ? "" : "s"} below first; they break Enforce Unity Gateway. ` : "no blockers. Move the callers, then scan again before you enforce. "}
        <span className="row">
          <button className="btn secondary sm" onClick={() => onTab("code")} disabled={!fixes}>Code fixes ({fmt(fixes)})</button>
          <button className="btn secondary sm" onClick={() => onTab("callers")} disabled={!callers}>Callers ({fmt(callers)})</button>
        </span>
      </div>
      {gaps.length > 0 && (
        <Card title="Incomplete scan" note="Fix access or narrow the folders, then scan again.">
          <Table label="Incomplete scan surfaces" rows={gaps.map(([k, v]) => ({ surface: k, status: v }))} columns={[{ key: "surface", label: "Surface" }, { key: "status", label: "Status" }]} />
        </Card>
      )}
      <Card title="Blockers" note="These break when Enforce Unity Gateway is turned on.">
        <Table label="Blockers" rows={r.blockers || []} empty={<Empty title="No blockers" />} columns={[
          { key: "type", label: "Type", render: (b) => <Badge value={b.type} tone="bad" /> },
          { key: "item", label: "Item", render: (b) => <code className="wrap">{b.item}</code> },
          { key: "detail", label: "What to do", render: (b) => <span className="small">{b.detail}</span> },
        ]} />
      </Card>
      <Card title="Warnings by type" note="Code that breaks if it still runs after Enforce, and external model and Provisioned Throughput traffic that retires with v1.">
        <Table label="Warnings by type" rows={warnCounts} empty={<Empty title="No warnings" />} columns={[{ key: "type", label: "Type" }, { key: "n", label: "Count", num: true }]} />
      </Card>
      <Card title="Can be closed now" note="External model endpoints with no traffic, dependents or references.">
        {candidates.length === 0 ? <Empty title="None" /> : (
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
        {actions.map((a) => <button key={a} className="btn secondary sm" aria-pressed={action === a} onClick={() => setAction(a)}>{a.replace(/_/g, " ")}</button>)}
      </div>
      <Table search label="Endpoint plan" rows={rows} empty="No legacy endpoints in this workspace" columns={[
        { key: "legacy_endpoint", label: "Legacy endpoint", render: (p) => <code>{p.legacy_endpoint}</code> },
        { key: "kind", label: "Kind" },
        { key: "action", label: "Plan", render: (p) => <Badge value={p.action} tone={p.action === "create_model_service" ? "info" : p.action === "use_system_ai" ? "good" : "neutral"} /> },
        { key: "target_service", label: "Target", render: (p) => p.target_service ? <><code>{p.target_service}</code> {p.target_status === "exists" && <Badge value="exists" tone="good" />}</> : "-" },
        { key: "requests_window", label: "Requests", num: true, render: (p) => fmt(p.requests_window) },
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
  return (
    <div className="table-tools">
      <label className="sr-only" htmlFor={`f-${label.replace(/\W+/g, "-")}`}>{label}</label>
      <input id={`f-${label.replace(/\W+/g, "-")}`} type="search" className="search" placeholder={label} value={value} onChange={(e) => onChange(e.target.value)} />
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
 *  is never split across pages; "Show more" extends the list. */
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
  return (
    <div className="stack">
      <p className="muted small"><Badge value="auto" tone="good" /> mechanical rewrite · <Badge value="review" tone="warn" /> check before applying. Edit the source (and its Git repo), then scan again. Lines with a credential get no proposed fix.</p>
      <FilterInput label="Filter by path" value={q} onChange={setQ} updating={!!res.loading && !!res.data} />
      {groups.length === 0 && <Empty title="No matches" />}
      {groups.map(([asset, items]) => (
        <details key={asset} className="diff" open={groups.length <= 10}>
          <summary><code className="wrap">{asset}</code> <span className="muted small">{items.length} line{items.length === 1 ? "" : "s"}</span></summary>
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
          <span className="small muted">Showing {fmt(rows.length)} of {fmt(total)} lines. The last file may continue below.</span>
          <button className="btn secondary sm" onClick={() => setLimit(Math.min(1000, limit + 200))} disabled={limit >= 1000 || res.loading}>Show more</button>
        </div>
      )}
    </div>
  );
}
