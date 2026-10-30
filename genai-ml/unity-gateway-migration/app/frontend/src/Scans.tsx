import { useEffect, useMemo, useState } from "react";
import { api, fmt, jobRunning, useApi, useJob, usePollWhileRunning } from "./api";
import { Badge, Card, CopyButton, Empty, ErrorBox, JobLine, Kpi, Loading, Table } from "./ui";

const STATUS_TEXT: Record<string, string> = {
  READY: "Nothing blocks Enforce Unity Gateway in this workspace.",
  READY_WITH_WARNINGS: "Nothing breaks when you enforce, but some work remains (see warnings).",
  INCOMPLETE: "Part of the scan failed or was skipped, or traffic couldn't be confirmed, so readiness can't be decided yet.",
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

  const start = async () => {
    setStartErr(null);
    if (!(form.days >= 1 && form.days <= 365)) { setStartErr("The traffic window must be between 1 and 365 days."); return; }
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
      <h2>Workspace scans</h2>
      <Card title="Start a scan" note="Reads your workspace only (results are saved to the results schema). Inventories legacy endpoints, reads traffic from system tables, scans notebooks, jobs, queries, dashboards, apps, Genie Agents, pipelines, SQL functions, AI Search and Agent Bricks, and builds the plan. Takes a few minutes.">
        <div className="form">
          <label>Traffic window (days)<input type="number" min={1} max={365} value={Number.isNaN(form.days) ? "" : form.days} onChange={(e) => setForm({ ...form, days: e.target.valueAsNumber })} /></label>
          <label>Extra folders to scan (optional)<input placeholder="blank = /Users, /Shared, /Repos" value={form.scan_roots} onChange={(e) => setForm({ ...form, scan_roots: e.target.value })} /></label>
          <label>Target catalog<input value={form.target_catalog} onChange={(e) => setForm({ ...form, target_catalog: e.target.value })} /></label>
          <label>Target schema<input value={form.target_schema} onChange={(e) => setForm({ ...form, target_schema: e.target.value })} /></label>
          <button onClick={start} disabled={!operator || starting || jobRunning(jobId, job)} title={operator ? "" : "Only the app's operators can start jobs"}>Start scan</button>
        </div>
        <p className="muted small">The target catalog and schema are where new model services would be created; use the same values when you apply.</p>
        {jobId && <JobLine state={job} label="Scan" />}
        {startErr && <ErrorBox error={startErr} />}
      </Card>
      <Card title="Scan history" actions={<button className="ghost small" onClick={list.reload}>Reload</button>}>
        {list.loading && !list.data ? <Loading /> : list.error ? <ErrorBox error={list.error} /> : (
          <Table rows={list.data || []} empty="No scans yet. Start one above." columns={[
            { key: "started_at", label: "Started", render: (r) => <button className="link" onClick={() => setSelected(r.run_id)}>{String(r.started_at).slice(0, 16)}</button> },
            { key: "status", label: "Scan status", render: (r) => <><Badge value={r.status} />{r.error && r.status === "FAILED" && <div className="small text-bad">{String(r.error).slice(0, 120)}</div>}</> },
            { key: "readiness", label: "Readiness", render: (r) => r.readiness ? <Badge value={r.readiness} /> : "-" },
            { key: "endpoints", label: "Endpoints", num: true },
            { key: "client_references", label: "Code refs", num: true },
            { key: "days", label: "Window", num: true },
            { key: "requested_by", label: "Requested by" },
            { key: "run_id", label: "", render: (r) => <button className="ghost small" onClick={() => setSelected(r.run_id)}>Open</button> },
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
  if (loading && !data) return <Loading text="Loading scan" />;
  if (error?.startsWith("404")) return <Card title="Scan"><Loading text="The scan job is starting; results appear here when it finishes" /><button className="ghost small" onClick={reload}>Reload</button></Card>;
  if (error) return <Card title="Scan"><ErrorBox error={error} /><button className="ghost small" onClick={reload}>Retry</button></Card>;
  const m = data.meta, r = data.readiness || {};
  if (m.status !== "SUCCEEDED") {
    return (
      <Card title="Scan" actions={<button className="ghost small" onClick={reload}>Reload</button>}>
        <p><Badge value={m.status} /> started {String(m.started_at).slice(0, 16)} by {m.requested_by}</p>
        {m.error && <ErrorBox error={m.error} />}
      </Card>
    );
  }
  const tabs = [["readiness", "Readiness"], ["endpoints", `Endpoints (${data.plan.length})`], ["callers", `Callers (${data.callers.length})`],
    ["code", `Code fixes (${fmt(data.ref_counts?.fixes)})`], ["refs", `All references (${fmt(data.ref_counts?.all)})`]];
  return (
    <section className="card">
      <header className="card-head">
        <div>
          <h3>Scan of {m.workspace_url?.replace("https://", "")}</h3>
          <p className="muted small">Finished {String(m.finished_at).slice(0, 16)} UTC, traffic window {m.days} days, toolkit {m.toolkit_version}, requested by {m.requested_by}</p>
        </div>
        <button onClick={() => onApply(runId)}>Plan apply from this scan</button>
      </header>
      <div className={`banner ${r.status === "READY" ? "good" : r.status === "BLOCKED" ? "bad" : "warn"}`}>
        <Badge value={r.status} /> <span>{STATUS_TEXT[r.status] || ""}</span>
      </div>
      <nav className="subtabs" role="tablist">
        {tabs.map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>{l}</button>)}
      </nav>
      {tab === "readiness" && <Readiness r={r} />}
      {tab === "endpoints" && <Endpoints plan={data.plan} providers={data.providers} />}
      {tab === "callers" && (
        <Table search rows={data.callers} empty="No legacy traffic in the window." columns={[
          { key: "endpoint_name", label: "Endpoint", render: (c) => <code>{c.endpoint_name}</code> },
          { key: "requester_name", label: "Caller" },
          { key: "requests", label: "Requests", num: true, render: (c) => fmt(c.requests) },
          { key: "last_request", label: "Last request", render: (c) => String(c.last_request || "").slice(0, 16) },
          { key: "linked_code", label: "Code found", render: (c) => (c.linked_code || []).length ? (c.linked_code || []).slice(0, 3).map((x: string) => <div key={x} className="small"><code>{x}</code></div>) : <span className="muted small">not found in this caller's folders: check jobs, external apps, Git repos and laptops</span> },
        ]} />
      )}
      {tab === "code" && <CodeFixes runId={runId} />}
      {tab === "refs" && <AllRefs runId={runId} />}
    </section>
  );
}

function Readiness({ r }: { r: any }) {
  const gaps = Object.entries(r.coverage_gaps || {});
  const warnCounts = useMemo(() => {
    const c: Record<string, number> = {};
    (r.warnings || []).forEach((w: any) => (c[w.type] = (c[w.type] || 0) + 1));
    return Object.entries(c).map(([type, n]) => ({ type, n }));
  }, [r]);
  return (
    <div className="stack">
      <div className="kpis">
        <Kpi label="Blockers" value={(r.blockers || []).length} tone={(r.blockers || []).length ? "bad" : "good"} />
        <Kpi label="Warnings" value={(r.warnings || []).length} tone={(r.warnings || []).length ? "warn" : "good"} />
        <Kpi label="Scan gaps" value={gaps.length} tone={gaps.length ? "warn" : "good"} sub={r.traffic_status && r.traffic_status !== "ok" ? "traffic not confirmed" : "traffic confirmed"} />
        <Kpi label="Can be closed now" value={(r.rate_limit_zero_candidates || []).length} sub="external model endpoints" />
      </div>
      {gaps.length > 0 && (
        <Card title="Incomplete scan" note="Fix access or narrow the folders, then scan again.">
          <Table rows={gaps.map(([k, v]) => ({ surface: k, status: v }))} columns={[{ key: "surface", label: "Surface" }, { key: "status", label: "Status" }]} />
        </Card>
      )}
      <Card title="Blockers" note="These break something when Enforce Unity Gateway is turned on.">
        <Table rows={r.blockers || []} empty="No blockers." columns={[
          { key: "type", label: "Type", render: (b) => <Badge value={b.type} tone="bad" /> },
          { key: "item", label: "Item", render: (b) => <code className="wrap">{b.item}</code> },
          { key: "detail", label: "What to do", render: (b) => <span className="small">{b.detail}</span> },
        ]} />
      </Card>
      <Card title="Warnings by type" note="Code that will break if it still runs after Enforce, and traffic on external model / PT endpoints, which keeps working after Enforce but retires with v1.">
        <Table rows={warnCounts} empty="No warnings." columns={[{ key: "type", label: "Type" }, { key: "n", label: "Count", num: true }]} />
      </Card>
      <Card title="Can be closed now" note="External model endpoints with no traffic, no dependents and no references in a complete scan. These commands CHANGE the legacy endpoint (the app never runs them for you): close sets its rate limit to 0 and keeps its other settings, undo restores the current config. Confirm with the owner first, and run them with the Databricks CLI.">
        {(r.rate_limit_zero_candidates || []).length === 0 ? <Empty>None.</Empty> : (r.rate_limit_zero_candidates || []).map((c: any) => {
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
      <div className="row">
        <span className="small muted">Show:</span>
        <button className={`ghost small ${!action ? "active" : ""}`} onClick={() => setAction("")}>All</button>
        {actions.map((a) => <button key={a} className={`ghost small ${action === a ? "active" : ""}`} onClick={() => setAction(a)}>{a.replace(/_/g, " ")}</button>)}
      </div>
      <Table search rows={rows} columns={[
        { key: "legacy_endpoint", label: "Legacy endpoint", render: (p) => <code>{p.legacy_endpoint}</code> },
        { key: "kind", label: "Kind" },
        { key: "action", label: "Plan", render: (p) => <Badge value={p.action} tone={p.action === "create_model_service" ? "info" : p.action === "use_system_ai" ? "good" : "neutral"} /> },
        { key: "target_service", label: "Target", render: (p) => p.target_service ? <><code>{p.target_service}</code> {p.target_status === "exists" && <Badge value="exists" tone="good" />}</> : "-" },
        { key: "requests_window", label: "Requests", num: true, render: (p) => fmt(p.requests_window) },
        { key: "needs_human", label: "Needs a person", render: (p) => (Array.isArray(p.needs_human) ? p.needs_human : []).map((n: string, i: number) => <div key={i} className="small">{n}</div>) },
      ]} />
      {providers.length > 0 && (
        <Card title="Provider services the plan needs">
          <Table rows={providers} columns={[
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

/** One server-side page of a scan's references; the filter is applied in SQL, so large scans stay fast. */
function usePagedRefs(runId: string, kind: "all" | "fixes", pageSize: number) {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  useEffect(() => { const t = setTimeout(() => { setQuery(q); setPage(0); }, 400); return () => clearTimeout(t); }, [q]);
  const res = useApi<any>(`/api/scans/${runId}/refs?kind=${kind}&q=${encodeURIComponent(query)}&offset=${page * pageSize}&limit=${pageSize}`);
  const total = Number(res.data?.total || 0);
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const pager = pages > 1 && (
    <div className="pager">
      <button disabled={page === 0 || res.loading} onClick={() => setPage(page - 1)}>Prev</button>
      <span className="muted small">Page {page + 1} of {pages} ({fmt(total)} rows)</span>
      <button disabled={page >= pages - 1 || res.loading} onClick={() => setPage(page + 1)}>Next</button>
    </div>
  );
  return { ...res, rows: (res.data?.rows || []) as any[], total, q, setQ, pager };
}

function AllRefs({ runId }: { runId: string }) {
  const r = usePagedRefs(runId, "all", 100);
  return (
    <div>
      <input className="search" placeholder="Filter (path, endpoint, pattern)..." aria-label="Filter references" value={r.q} onChange={(e) => r.setQ(e.target.value)} />
      {r.error ? <ErrorBox error={r.error} /> : r.loading && !r.data ? <Loading text="Loading references" /> : (
        <Table rows={r.rows} pageSize={100} label="Client references" empty={r.q ? "No references match." : "No references found."} columns={[
          { key: "asset_type", label: "Type" },
          { key: "asset", label: "Where", render: (x) => <><code className="wrap">{x.asset}</code>{x.line ? <span className="muted small">:{x.line}</span> : null}</> },
          { key: "pattern", label: "Pattern" },
          { key: "legacy_endpoint", label: "Endpoint", render: (x) => x.legacy_endpoint ? <code>{x.legacy_endpoint}</code> : "-" },
          { key: "suggestion", label: "Suggestion", render: (x) => <span className="small">{x.suggestion}</span> },
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
  if (r.error) return <ErrorBox error={r.error} />;
  if (r.loading && !r.data) return <Loading text="Loading code fixes" />;
  if (r.total === 0 && !r.q) return <Empty>No proposed code changes.</Empty>;
  return (
    <div className="stack">
      <p className="muted small"><Badge value="auto" tone="good" /> mechanical rewrite &nbsp; <Badge value="review" tone="warn" /> check before applying. Nothing is changed for you: apply these in the source (and its Git repo), then scan again.</p>
      <p className="muted small">Lines that contain a credential get no proposed fix (edit them by hand); other credential-looking values show as &lt;hidden&gt;.</p>
      <input className="search" placeholder="Filter by path..." aria-label="Filter code fixes by path" value={r.q} onChange={(e) => r.setQ(e.target.value)} />
      {groups.length === 0 && <Empty>No fixes match.</Empty>}
      {groups.map(([asset, items]) => (
        <details key={asset} className="diff" open={groups.length <= 10}>
          <summary className="diff-head"><code className="wrap">{asset}</code> <span className="muted small">{items.length} line(s)</span></summary>
          {items.map((x, i) => (
            <div key={i} className="diff-item">
              <div className="small muted">line {x.line} <Badge value={x.fix_confidence} tone={x.fix_confidence === "auto" ? "good" : "warn"} /> <CopyButton text={x.fixed_line} /></div>
              <pre className="del">- {x.line_text}</pre>
              <pre className="add">+ {x.fixed_line}</pre>
            </div>
          ))}
        </details>
      ))}
      {r.pager}
    </div>
  );
}
