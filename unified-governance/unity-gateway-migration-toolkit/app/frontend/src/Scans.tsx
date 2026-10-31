import { useEffect, useMemo, useState } from "react";
import { api, fmt, jobRunning, useApi, useJob, usePollWhileRunning } from "./api";
import { Badge, Card, CopyButton, Empty, ErrorBox, ErrorState, ExportMenu, JobLine, Kpi, Notice, PageHeader, Pager, Skeleton, SkeletonCard, SkeletonTable, Table, Tabs } from "./ui";

const STATUS_TEXT: Record<string, string> = {
  READY: "Nothing blocks Enforce Unity Gateway in this workspace.",
  READY_WITH_WARNINGS: "Enforcing won't break anything, but some code still needs to change.",
  INCOMPLETE: "Part of the scan failed or traffic couldn't be confirmed, so readiness can't be decided yet.",
  BLOCKED: "Enforcing now would break something. Fix the blockers first.",
};

export default function Scans({ onApply, operator }: { onApply: (runId: string) => void; operator: boolean }) {
  const list = useApi<any[]>("/api/scans");
  const [selected, setSelected] = useState<string | null>(null);
  const [form, setForm] = useState({ days: 30, scan_roots: "", target_catalog: "ai_gateway", target_schema: "migrated" });
  const [jobId, setJobId] = useState<string | null>(null);
  const [startErr, setStartErr] = useState<string | null>(null);
  const [detailKey, setDetailKey] = useState(0);
  const [starting, setStarting] = useState(false);
  const job = useJob(jobId, () => { list.reload(); setDetailKey((k) => k + 1); });
  const daysOk = form.days >= 1 && form.days <= 365;
  const namesOk = /^[A-Za-z0-9_-]+$/.test(form.target_catalog) && /^[A-Za-z0-9_-]+$/.test(form.target_schema);
  const running = jobRunning(jobId, job);

  const start = async () => {
    setStartErr(null);
    setStarting(true);
    try {
      const r = await api("/api/scans", { method: "POST", body: JSON.stringify(form) });
      setJobId(r.job_run_id);
      setSelected(r.run_id);
    } catch (e: any) {
      setStartErr(e.message);
    } finally {
      setStarting(false);
    }
  };

  return (
    <div className="stack">
      <PageHeader title="Workspace scans" description="A scan reads this workspace (endpoints, traffic and code) and saves the results. It takes a few minutes." />
      <Card title="Start a scan" id="start-scan">
        <form className="form" onSubmit={(e) => { e.preventDefault(); if (daysOk && namesOk) start(); }}>
          <label className="field">Traffic window (days)
            <input type="number" min={1} max={365} required aria-invalid={!daysOk} aria-describedby={!daysOk ? "days-err" : undefined}
                   value={Number.isNaN(form.days) ? "" : form.days} onChange={(e) => setForm({ ...form, days: e.target.valueAsNumber })} />
          </label>
          <label className="field">Extra folders (optional)
            <input placeholder="/Shared/team, /Repos/app" value={form.scan_roots} onChange={(e) => setForm({ ...form, scan_roots: e.target.value })} />
          </label>
          <label className="field">Target catalog
            <input required aria-invalid={!/^[A-Za-z0-9_-]+$/.test(form.target_catalog)} value={form.target_catalog} onChange={(e) => setForm({ ...form, target_catalog: e.target.value })} />
          </label>
          <label className="field">Target schema
            <input required aria-invalid={!/^[A-Za-z0-9_-]+$/.test(form.target_schema)} value={form.target_schema} onChange={(e) => setForm({ ...form, target_schema: e.target.value })} />
          </label>
          <button type="submit" className="btn" disabled={!operator || starting || running || !daysOk || !namesOk}>
            {starting || running ? "Scanning…" : "Start scan"}
          </button>
        </form>
        {!daysOk && <p id="days-err" className="small text-bad">Use a window between 1 and 365 days.</p>}
        {!namesOk && <p className="small text-bad">Catalog and schema names can use letters, digits, _ and -.</p>}
        <p className="muted small">Folders default to /Users, /Shared and /Repos. The target is where apply would create model services; create that schema before you apply.</p>
        {!operator && <p className="muted small">View only: ask an operator to start scans.</p>}
        {jobId && <JobLine state={job} label="Scan" done="Results are below." />}
        {startErr && <ErrorBox error={startErr} />}
      </Card>
      <Card title="Scan history" actions={<button className="btn secondary sm" onClick={list.reload} disabled={list.loading}>Reload</button>}>
        {list.loading && !list.data ? <SkeletonTable rows={4} label="Loading scan history" /> : list.error ? <ErrorState error={list.error} onRetry={list.reload} /> : (
          <Table label="Scan history" rows={list.data || []} empty={<Empty title="No scans yet">Start a scan above to see readiness, callers and code fixes.</Empty>} columns={[
            { key: "started_at", label: "Started", render: (r) => <button className="btn link" onClick={() => setSelected(r.run_id)} aria-label={`Open scan started ${String(r.started_at).slice(0, 16)}`}>{String(r.started_at).slice(0, 16)}</button> },
            { key: "workspace_url", label: "Workspace", render: (r) => <span className="small">{r.workspace_url?.replace("https://", "") || "-"}</span> },
            { key: "status", label: "Status", render: (r) => <><Badge value={r.status} />{r.error && r.status === "FAILED" && <div className="small text-bad">{String(r.error).slice(0, 120)}</div>}</> },
            { key: "readiness", label: "Readiness", render: (r) => r.readiness ? <Badge value={r.readiness} /> : "-" },
            { key: "endpoints", label: "Endpoints", num: true, render: (r) => fmt(r.endpoints) },
            { key: "client_references", label: "Code refs", num: true, render: (r) => fmt(r.client_references) },
            { key: "requested_by", label: "By" },
          ]} />
        )}
      </Card>
      {selected && <ScanDetail key={`${selected}-${detailKey}`} runId={selected} onApply={onApply} />}
    </div>
  );
}

function ScanDetail({ runId, onApply }: { runId: string; onApply: (runId: string) => void }) {
  const { data, error, loading, reload } = useApi<any>(`/api/scans/${runId}`);
  const [tab, setTab] = useState("readiness");
  usePollWhileRunning(data?.meta?.status, error, reload);
  if (loading && !data) return <SkeletonCard title="Loading scan" />;
  if (error?.startsWith("404") || data?.meta?.status === "RUNNING") {
    return (
      <Card title="Scan in progress">
        <Notice tone="info">The scan is running. Results appear here when it finishes; this page checks automatically.</Notice>
        <Skeleton lines={4} label="Waiting for scan results" />
      </Card>
    );
  }
  if (error) return <Card title="Scan"><ErrorState error={error} onRetry={reload} title="Couldn't load this scan" /></Card>;
  const m = data.meta, r = data.readiness || {};
  if (m.status !== "SUCCEEDED") {
    return (
      <Card title="Scan" actions={<button className="btn secondary sm" onClick={reload}>Reload</button>}>
        <Notice tone="error" title={`Scan ${String(m.status).toLowerCase()}`}>{m.error || "The scan didn't finish. Check the job run, fix the cause and start a new scan."}</Notice>
        <p className="muted small">Started {String(m.started_at).slice(0, 16)} UTC by {m.requested_by}</p>
      </Card>
    );
  }
  const base = `/api/scans/${runId}/export`;
  const tabs = [["readiness", "Readiness"], ["endpoints", `Endpoints (${data.plan.length})`], ["callers", `Callers (${data.callers.length})`],
    ["code", count("Code fixes", data.ref_counts?.fixes)], ["refs", count("All references", data.ref_counts?.all)]] as const;
  return (
    <Card title={`Scan of ${m.workspace_url?.replace("https://", "")}`}
          note={`Finished ${String(m.finished_at).slice(0, 16)} UTC · ${m.days}-day window · by ${m.requested_by}`}
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
      <Tabs label="Scan results" tabs={tabs} value={tab} onChange={setTab} />
      <div role="tabpanel">
        {tab === "readiness" && <Readiness r={r} />}
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

function Readiness({ r }: { r: any }) {
  const gaps = Object.entries(r.coverage_gaps || {});
  const warnCounts = useMemo(() => {
    const c: Record<string, number> = {};
    (r.warnings || []).forEach((w: any) => (c[w.type] = (c[w.type] || 0) + 1));
    return Object.entries(c).map(([type, n]) => ({ type, n }));
  }, [r]);
  const candidates = r.rate_limit_zero_candidates || [];
  return (
    <div className="stack">
      <div className="kpis">
        <Kpi label="Blockers" value={(r.blockers || []).length} tone={(r.blockers || []).length ? "bad" : "good"} />
        <Kpi label="Warnings" value={(r.warnings || []).length} tone={(r.warnings || []).length ? "warn" : "good"} />
        <Kpi label="Scan gaps" value={gaps.length} tone={gaps.length ? "warn" : "good"} sub={r.traffic_status && r.traffic_status !== "ok" ? "traffic not confirmed" : "traffic confirmed"} />
        <Kpi label="Can be closed now" value={candidates.length} sub="external model endpoints" />
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
      <Card title="Warnings by type" note="Code that breaks if it still runs after Enforce, and external model / PT traffic that retires with v1.">
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

function FilterInput({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  return (
    <div className="table-tools">
      <label className="sr-only" htmlFor={`f-${label}`}>{label}</label>
      <input id={`f-${label}`} type="search" className="search" placeholder={label} value={value} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

function AllRefs({ runId }: { runId: string }) {
  const r = usePagedRefs(runId, "all", 100);
  return (
    <div>
      <FilterInput label="Filter by path, endpoint or pattern" value={r.q} onChange={r.setQ} />
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

function CodeFixes({ runId }: { runId: string }) {
  const r = usePagedRefs(runId, "fixes", 200);
  const groups = useMemo(() => {
    const g: Record<string, any[]> = {};
    r.rows.forEach((x) => (g[x.asset] = g[x.asset] || []).push(x));
    return Object.entries(g);
  }, [r.rows]);
  if (r.error) return <ErrorState error={r.error} onRetry={r.reload} />;
  if (r.loading && !r.data) return <SkeletonTable label="Loading code fixes" />;
  if (r.total === 0 && !r.q) return <Empty title="No code changes needed">No references in this workspace need a rewrite.</Empty>;
  return (
    <div className="stack">
      <p className="muted small"><Badge value="auto" tone="good" /> mechanical rewrite · <Badge value="review" tone="warn" /> check before applying. Edit the source (and its Git repo), then scan again. Lines with a credential get no proposed fix.</p>
      <FilterInput label="Filter by path" value={r.q} onChange={r.setQ} />
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
      {r.pager}
    </div>
  );
}
