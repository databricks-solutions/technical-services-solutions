import { useEffect, useMemo, useState } from "react";
import { api, fmt, jobRunning, useApi, useJob, usePollWhileRunning } from "./api";
import { Badge, Card, Confirm, Empty, ErrorBox, ErrorState, ExportMenu, JobLine, Notice, PageHeader, Skeleton, SkeletonCard, SkeletonTable, Table } from "./ui";

export default function Apply({ scanRunId, setScanRunId, operator }: { scanRunId: string | null; setScanRunId: (id: string) => void; operator: boolean }) {
  const scans = useApi<any[]>("/api/scans");
  const history = useApi<any[]>("/api/applies");
  const succeeded = (scans.data || []).filter((s) => s.status === "SUCCEEDED");
  useEffect(() => {
    if (!scanRunId && succeeded.length) setScanRunId(succeeded[0].run_id);
  }, [scanRunId, succeeded.length]);
  const [openApply, setOpenApply] = useState<string | null>(null);
  const [detailKey, setDetailKey] = useState(0);
  const refresh = () => { history.reload(); setDetailKey((k) => k + 1); };

  return (
    <div className="stack">
      <PageHeader title="Apply" description="Creates Unity Gateway provider services, model services and grants for external model and Provisioned Throughput endpoints. Legacy endpoints are never changed. databricks-* endpoints need nothing: their system.ai services already exist." />
      <Card title="1. Choose a scan">
        {scans.loading && !scans.data ? <Skeleton lines={1} label="Loading scans" /> : scans.error ? <ErrorState error={scans.error} onRetry={scans.reload} /> : succeeded.length === 0 ? (
          <Empty title="No finished scans">Run a workspace scan first (Scans tab); apply uses its plan.</Empty>
        ) : (
          <label className="field">Scan
            <select value={scanRunId || ""} onChange={(e) => setScanRunId(e.target.value)}>
              {succeeded.map((s) => <option key={s.run_id} value={s.run_id}>{String(s.started_at).slice(0, 16)} · {s.workspace_url?.replace("https://", "")} · {s.readiness}</option>)}
            </select>
          </label>
        )}
      </Card>
      {scanRunId && <Planner key={scanRunId} operator={operator} scanRunId={scanRunId} onStarted={(id) => setOpenApply(id)} onDone={refresh} />}
      <Card title="History" actions={<button className="btn secondary sm" onClick={history.reload} disabled={history.loading}>Reload</button>}>
        {history.loading && !history.data ? <SkeletonTable rows={3} label="Loading apply history" /> : history.error ? <ErrorState error={history.error} onRetry={history.reload} /> : (
          <Table label="Apply history" rows={history.data || []} empty={<Empty title="No apply runs yet">Dry runs, executes and rollbacks appear here.</Empty>} columns={[
            { key: "started_at", label: "Started", render: (r) => <button className="btn link" onClick={() => setOpenApply(r.apply_id)} aria-label={`Open ${r.mode} run from ${String(r.started_at).slice(0, 16)}`}>{String(r.started_at).slice(0, 16)}</button> },
            { key: "mode", label: "Mode", render: (r) => <Badge value={r.mode} tone={r.mode === "execute" ? "bad" : r.mode === "rollback" ? "warn" : "info"} /> },
            { key: "status", label: "Status", render: (r) => <Badge value={r.status} /> },
            { key: "endpoints", label: "Endpoints", render: (r) => <span className="small">{r.mode === "rollback" ? `rollback of ${String(r.rollback_of).slice(0, 8)}` : r.endpoints}</span> },
            { key: "summary", label: "Result", sortable: false, render: (r) => <Summary s={r.summary} /> },
            { key: "requested_by", label: "By" },
          ]} />
        )}
      </Card>
      {openApply && <ApplyDetail key={`${openApply}-${detailKey}`} operator={operator} applyId={openApply} onRolledBack={refresh} onOpen={setOpenApply} onFinished={history.reload} />}
    </div>
  );
}

function Summary({ s }: { s: string }) {
  let o: Record<string, number> = {};
  try { o = JSON.parse(s || "{}"); } catch { /* empty */ }
  return <span className="small">{Object.entries(o).map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(", ") || "-"}</span>;
}

function Planner({ scanRunId, onStarted, onDone, operator }: { scanRunId: string; onStarted: (id: string) => void; onDone: () => void; operator: boolean }) {
  const { data, error, loading, reload } = useApi<any>(`/api/scans/${scanRunId}`);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [secretMode, setSecretMode] = useState<"uc" | "read">("uc");
  const [ucMap, setUcMap] = useState("{}");
  const [grants, setGrants] = useState(true);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [lastMode, setLastMode] = useState<"dry_run" | "execute">("dry_run");
  const job = useJob(jobId, onDone);
  const candidates = useMemo(() => (data?.plan || []).filter((p: any) => p.action === "create_model_service"), [data]);
  const secrets = useMemo(() => Array.from(new Set((data?.providers || []).flatMap((p: any) => (Array.isArray(p.secrets) ? p.secrets : [])))), [data]);
  useEffect(() => {
    if (secrets.length) setUcMap(JSON.stringify(Object.fromEntries(secrets.map((s: any) => [s, `secrets/${data?.meta?.target_catalog || "<catalog>"}.${data?.meta?.target_schema || "<schema>"}.${String(s).split("/").pop()!.replace(/[^A-Za-z0-9_-]/g, "_")}`])), null, 1));
  }, [secrets.join(",")]);
  if (loading && !data) return <SkeletonCard title="2. Choose endpoints and options" />;
  if (error) return <Card title="2. Choose endpoints and options"><ErrorState error={error} onRetry={reload} title="Couldn't load the plan" /></Card>;
  const meta = data.meta;
  const running = jobRunning(jobId, job);
  const disabled = !operator || !chosen.size || busy || running;

  const start = async (mode: "dry_run" | "execute") => {
    setErr(null);
    let map = {};
    if (secretMode === "uc") {
      try { map = JSON.parse(ucMap || "{}"); } catch { setErr("The secret map isn't valid JSON."); return; }
      if (JSON.stringify(map).includes("<catalog>")) { setErr("Replace <catalog>.<schema> in the secret map with your Unity Catalog secret names."); return; }
    }
    setBusy(true);
    try {
      const r: any = await api("/api/applies", { method: "POST", body: JSON.stringify({
        mode, scan_run_id: scanRunId, endpoints: Array.from(chosen), target_catalog: meta.target_catalog,
        target_schema: meta.target_schema, uc_secret_map: secretMode === "uc" ? map : {},
        allow_secret_read: secretMode === "read", grants, confirm: mode === "execute" ? "EXECUTE" : "" }) });
      setLastMode(mode);
      setJobId(r.job_run_id);
      onStarted(r.apply_id);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  };

  return (
    <Card title="2. Choose endpoints and options" note={<>Target <code>{meta.target_catalog}.{meta.target_schema}</code> (from the scan). It must exist, and the jobs' identity needs <code>CREATE SERVICE</code> on it.</>}>
      {candidates.length === 0 ? <Empty title="Nothing to create">This scan has no external model or Provisioned Throughput endpoints.</Empty> : (
        <>
          <Table label="Endpoints apply can migrate" rows={candidates} pageSize={50} tools={<>
            <span className="small muted" aria-live="polite">{chosen.size} of {candidates.length} selected</span>
            <button className="btn secondary sm" onClick={() => setChosen(new Set(candidates.map((p: any) => p.legacy_endpoint)))} disabled={chosen.size === candidates.length}>Select all</button>
            <button className="btn secondary sm" onClick={() => setChosen(new Set())} disabled={!chosen.size}>Clear</button>
          </>} columns={[
            { key: "pick", label: "", width: "36px", sortable: false, render: (p) => <input type="checkbox" aria-label={`Select ${p.legacy_endpoint}`} checked={chosen.has(p.legacy_endpoint)} onChange={(e) => { const s = new Set(chosen); e.target.checked ? s.add(p.legacy_endpoint) : s.delete(p.legacy_endpoint); setChosen(s); }} /> },
            { key: "legacy_endpoint", label: "Legacy endpoint", render: (p) => <code>{p.legacy_endpoint}</code> },
            { key: "kind", label: "Kind" },
            { key: "target_service", label: "Creates", render: (p) => <><code>{p.target_service}</code> {p.target_status === "exists" && <Badge value="exists" tone="good" />}</> },
            { key: "requests_window", label: "Requests", num: true, render: (p) => fmt(p.requests_window) },
            { key: "needs_human", label: "Notes", sortable: false, render: (p) => (Array.isArray(p.needs_human) ? p.needs_human : []).map((n: string, i: number) => <div key={i} className={`small ${n.startsWith("BLOCKS APPLY") ? "text-bad" : ""}`}>{n}</div>) },
          ]} />
          <div className="panel">
            <fieldset>
              <legend>Provider API keys</legend>
              <label className="choice"><input type="radio" name="secret-mode" checked={secretMode === "uc"} onChange={() => setSecretMode("uc")} /> <span>Reference Unity Catalog secrets (recommended)</span></label>
              {secretMode === "uc" && (
                <label className="field"><span>Secret map: workspace secret (<code>scope/key</code>) to Unity Catalog secret (<code>secrets/catalog.schema.name</code>). Create the UC secrets first.</span>
                  <textarea rows={Math.max(3, secrets.length + 2)} value={ucMap} onChange={(e) => setUcMap(e.target.value)} spellCheck={false} />
                </label>
              )}
              <label className="choice"><input type="radio" name="secret-mode" checked={secretMode === "read"} onChange={() => setSecretMode("read")} /> <span>Copy the workspace secret values into the provider service</span></label>
              {secretMode === "read" && <Notice tone="warning">The key is then stored in the provider service, and the identity that runs the apply job reads it (even if you can't). Prefer Unity Catalog secrets.</Notice>}
            </fieldset>
            <label className="choice"><input type="checkbox" checked={grants} onChange={(e) => setGrants(e.target.checked)} /> <span>Copy legacy endpoint permissions as EXECUTE / MANAGE grants</span></label>
          </div>
          <div className="row">
            <button className="btn" disabled={disabled} onClick={() => start("dry_run")}>{busy && lastMode === "dry_run" ? "Starting…" : "Dry run"}</button>
            <button className="btn danger" disabled={disabled} onClick={() => setConfirming(true)}>Execute…</button>
            {!operator && <span className="muted small">View only: ask an operator to run apply.</span>}
            {operator && !chosen.size && <span className="muted small">Select at least one endpoint.</span>}
          </div>
          {jobId && <JobLine state={job} label={lastMode === "execute" ? "Execute" : "Dry run"} done="See the run below for every object." />}
          {err && <ErrorBox error={err} />}
          {confirming && (
            <Confirm word="EXECUTE" title="Execute" busy={busy} onCancel={() => setConfirming(false)} onConfirm={() => start("execute")}
                     body={<>
                       <p>Create these model services (and the provider services they need) in <code>{meta.target_catalog}.{meta.target_schema}</code>:</p>
                       <ul className="small">{candidates.filter((p: any) => chosen.has(p.legacy_endpoint)).slice(0, 12).map((p: any) => <li key={p.legacy_endpoint}><code>{p.target_service}</code> from <code>{p.legacy_endpoint}</code></li>)}{chosen.size > 12 && <li>and {chosen.size - 12} more</li>}</ul>
                       <p className="small">Grants: <b>{grants ? "copied from legacy permissions" : "none"}</b>. Keys: <b>{secretMode === "uc" ? "Unity Catalog secret references" : "copied from workspace secrets"}</b>. You can roll back from the history.</p>
                     </>} />
          )}
        </>
      )}
    </Card>
  );
}

function ApplyDetail({ applyId, onRolledBack, onOpen, onFinished, operator }: { applyId: string; onRolledBack: () => void; onOpen: (id: string) => void; onFinished: () => void; operator: boolean }) {
  const { data, error, loading, reload } = useApi<any>(`/api/applies/${applyId}`);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(jobId, onRolledBack);
  usePollWhileRunning(data?.meta?.status, error, reload, onFinished);
  const title = `Apply run ${applyId.slice(0, 8)}`;
  if (loading && !data) return <SkeletonCard title={title} />;
  if (error?.startsWith("404") || data?.meta?.status === "RUNNING") {
    return (
      <Card title={title}>
        <Notice tone="info">The job is running. Results appear here when it finishes; this page checks automatically.</Notice>
        <SkeletonTable rows={3} label="Waiting for apply results" />
      </Card>
    );
  }
  if (error) return <Card title={title}><ErrorState error={error} onRetry={reload} title="Couldn't load this run" /></Card>;
  const m = data.meta;
  const created = data.items.filter((i: any) => i.action === "created").length;
  const rollbacks: any[] = data.rollbacks || [];
  const rolledBack = rollbacks.find((r) => r.status === "SUCCEEDED" || r.status === "RUNNING");
  const canRollBack = operator && m.mode === "execute" && created > 0 && ["SUCCEEDED", "NEEDS_ATTENTION", "FAILED"].includes(m.status) && !rolledBack && !jobRunning(jobId, job);
  const rollback = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r: any = await api("/api/applies", { method: "POST", body: JSON.stringify({ mode: "rollback", rollback_of: applyId, confirm: "ROLLBACK" }) });
      setJobId(r.job_run_id);
      onOpen(r.apply_id);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  };
  const outcome = {
    SUCCEEDED: <Notice tone="success" title={`${m.mode === "dry_run" ? "Dry run" : m.mode === "rollback" ? "Rollback" : "Execute"} succeeded`}><Summary s={m.summary} /></Notice>,
    NEEDS_ATTENTION: <Notice tone="warning" title="Finished with items that need attention">Check the rows marked manual, error, mismatch or kept below. <Summary s={m.summary} /></Notice>,
    FAILED: <Notice tone="error" title="Run failed">{m.error || "The job ended without recording a result."}</Notice>,
  }[m.status as string];
  return (
    <Card title={title} note={`${m.mode.replace("_", " ")} by ${m.requested_by} · ${String(m.started_at).slice(0, 16)} UTC`}
          actions={<>
            <ExportMenu items={[{ href: `/api/applies/${applyId}/export`, label: "Results", hint: "CSV" }]} />
            {canRollBack && <button className="btn danger sm" onClick={() => setConfirming(true)}>Roll back…</button>}
          </>}>
      {outcome}
      {rolledBack && <p className="small">Rolled back by run <button className="btn link" onClick={() => onOpen(rolledBack.apply_id)}>{String(rolledBack.apply_id).slice(0, 8)}</button> ({String(rolledBack.status).toLowerCase()}).</p>}
      {jobId && <JobLine state={job} label="Rollback" />}
      {err && <ErrorBox error={err} />}
      <Table label="Apply results" rows={data.items} pageSize={50} empty={<Empty title="No objects">This run didn't create, change or check anything.</Empty>} columns={[
        { key: "type", label: "Object", render: (i) => i.type?.replace(/_/g, " ") },
        { key: "name", label: "Name", render: (i) => <code className="wrap">{i.name}</code> },
        { key: "action", label: "Result", render: (i) => <Badge value={i.action} /> },
        { key: "reason", label: "Details", sortable: false, render: (i) => <span className="small">{i.reason || (i.issues || []).join("; ") || (i.grants ? i.grants.map((g: any) => `${g.principal}: ${g.privileges.join("+")}`).join(", ") : "")}</span> },
      ]} />
      {confirming && (
        <Confirm word="ROLLBACK" title="Roll back" busy={busy} onCancel={() => setConfirming(false)} onConfirm={rollback}
                 body={<>
                   <p>Delete the {created} object{created === 1 ? "" : "s"} this run created:</p>
                   <ul className="small">{data.items.filter((i: any) => i.action === "created").slice(0, 12).map((i: any) => <li key={i.type + i.name}><code>{i.name}</code> ({String(i.type).replace(/_/g, " ")})</li>)}</ul>
                   <p className="small">Objects another run still uses are kept. Inference tables stay.</p>
                 </>} />
      )}
    </Card>
  );
}
