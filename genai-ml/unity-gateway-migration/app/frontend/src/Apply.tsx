import { useEffect, useMemo, useState } from "react";
import { api, fmt, jobRunning, useApi, useJob, usePollWhileRunning } from "./api";
import { Badge, Card, Confirm, Empty, ErrorBox, JobLine, Loading, Table } from "./ui";

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
      <h2>Apply</h2>
      <div className="alert info small">
        Apply creates Unity Gateway <b>provider services</b>, <b>model services</b> (destinations, fallback, rate limits,
        inference table) and <b>grants</b> for legacy <b>external model</b> and <b>Provisioned Throughput</b> endpoints.
        It never changes or deletes legacy endpoints, so callers keep working until their code moves. Databricks-hosted
        <code>databricks-*</code> endpoints need nothing new: their <code>system.ai</code> services already exist.
        Always start with a dry run. An execute run can be rolled back from the history: that deletes the services it
        created, and their grants go with them. Inference tables stay.
      </div>
      <Card title="1. Choose a scan">
        {scans.loading && !scans.data ? <Loading /> : scans.error ? <><ErrorBox error={scans.error} /><button className="ghost small" onClick={scans.reload}>Retry</button></> : succeeded.length === 0 ? <Empty>Run a workspace scan first (Scans tab).</Empty> : (
          <select aria-label="Scan to apply from" value={scanRunId || ""} onChange={(e) => setScanRunId(e.target.value)}>
            {succeeded.map((s) => <option key={s.run_id} value={s.run_id}>{String(s.started_at).slice(0, 16)}: {s.workspace_url?.replace("https://", "")} ({s.readiness})</option>)}
          </select>
        )}
      </Card>
      {scanRunId && <Planner key={scanRunId} operator={operator} scanRunId={scanRunId} onStarted={(id) => setOpenApply(id)} onDone={refresh} />}
      <Card title="History" actions={<button className="ghost small" onClick={history.reload}>Reload</button>}>
        {history.loading && !history.data ? <Loading /> : history.error ? <ErrorBox error={history.error} /> : (
          <Table rows={history.data || []} empty="No apply runs yet." columns={[
            { key: "started_at", label: "Started", render: (r) => String(r.started_at).slice(0, 16) },
            { key: "mode", label: "Mode", render: (r) => <Badge value={r.mode} tone={r.mode === "execute" ? "bad" : r.mode === "rollback" ? "warn" : "info"} /> },
            { key: "status", label: "Status", render: (r) => <Badge value={r.status} /> },
            { key: "endpoints", label: "Endpoints", render: (r) => <span className="small">{r.mode === "rollback" ? `rollback of ${String(r.rollback_of).slice(0, 8)}` : r.endpoints}</span> },
            { key: "summary", label: "Result", render: (r) => <Summary s={r.summary} /> },
            { key: "requested_by", label: "By" },
            { key: "apply_id", label: "", render: (r) => <button className="ghost small" onClick={() => setOpenApply(r.apply_id)}>Open</button> },
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
  const { data, error, loading } = useApi<any>(`/api/scans/${scanRunId}`);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [secretMode, setSecretMode] = useState<"uc" | "read">("uc");
  const [ucMap, setUcMap] = useState("{}");
  const [grants, setGrants] = useState(true);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const job = useJob(jobId, onDone);
  const candidates = useMemo(() => (data?.plan || []).filter((p: any) => p.action === "create_model_service"), [data]);
  const secrets = useMemo(() => Array.from(new Set((data?.providers || []).flatMap((p: any) => (Array.isArray(p.secrets) ? p.secrets : [])))), [data]);
  useEffect(() => {
    if (secrets.length) setUcMap(JSON.stringify(Object.fromEntries(secrets.map((s: any) => [s, `secrets/${data?.meta?.target_catalog || "<catalog>"}.${data?.meta?.target_schema || "<schema>"}.${String(s).split("/").pop()!.replace(/[^A-Za-z0-9_-]/g, "_")}`])), null, 1));
  }, [secrets.join(",")]);
  if (loading && !data) return <Loading text="Loading plan" />;
  if (error) return <ErrorBox error={error} />;
  const meta = data.meta;

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
    <Card title="2. Choose endpoints and options" note={`Target: ${meta.target_catalog}.${meta.target_schema} (from the scan). The schema must exist, and the job's identity needs CREATE SERVICE there.`}>
      {candidates.length === 0 ? <Empty>This scan has no external model or PT endpoints to create services for.</Empty> : (
        <>
          <Table rows={candidates} pageSize={50} columns={[
            { key: "pick", label: "", width: "32px", render: (p) => <input type="checkbox" aria-label={`Select ${p.legacy_endpoint}`} checked={chosen.has(p.legacy_endpoint)} onChange={(e) => { const s = new Set(chosen); e.target.checked ? s.add(p.legacy_endpoint) : s.delete(p.legacy_endpoint); setChosen(s); }} /> },
            { key: "legacy_endpoint", label: "Legacy endpoint", render: (p) => <code>{p.legacy_endpoint}</code> },
            { key: "kind", label: "Kind" },
            { key: "target_service", label: "Creates", render: (p) => <><code>{p.target_service}</code> {p.target_status === "exists" && <Badge value="exists" tone="good" />}</> },
            { key: "requests_window", label: "Requests", num: true, render: (p) => fmt(p.requests_window) },
            { key: "needs_human", label: "Notes", render: (p) => (Array.isArray(p.needs_human) ? p.needs_human : []).map((n: string, i: number) => <div key={i} className={`small ${n.startsWith("BLOCKS APPLY") ? "text-bad" : ""}`}>{n}</div>) },
          ]} />
          <div className="row">
            <button className="ghost small" onClick={() => setChosen(new Set(candidates.map((p: any) => p.legacy_endpoint)))}>Select all</button>
            <button className="ghost small" onClick={() => setChosen(new Set())}>Clear</button>
            <span className="muted small">{chosen.size} selected</span>
          </div>
          <div className="options">
            <div>
              <b className="small">Provider secrets</b>
              <label className="radio"><input type="radio" checked={secretMode === "uc"} onChange={() => setSecretMode("uc")} /> Unity Catalog secret references (recommended)</label>
              {secretMode === "uc" && <>
                <p className="muted small">JSON: each workspace secret the legacy endpoints use (<code>"scope/key"</code>) mapped to the Unity Catalog secret to reference (<code>"secrets/catalog.schema.name"</code>). Create the UC secrets first.</p>
                <textarea aria-label="Secret map" rows={Math.max(3, secrets.length + 2)} value={ucMap} onChange={(e) => setUcMap(e.target.value)} spellCheck={false} />
              </>}
              <label className="radio"><input type="radio" checked={secretMode === "read"} onChange={() => setSecretMode("read")} /> Read the workspace secret values at execute time with the jobs' identity and copy them into the provider service (never shown or logged)</label>
              {secretMode === "read" && <div className="alert info small">The key value is then stored in the Unity Gateway provider service itself, and the identity that runs the apply job reads the secret (even if you can't). Prefer Unity Catalog secret references.</div>}
            </div>
            <label className="radio"><input type="checkbox" checked={grants} onChange={(e) => setGrants(e.target.checked)} /> Grant EXECUTE / MANAGE from the legacy endpoint permissions</label>
          </div>
          <div className="row">
            <button disabled={!operator || !chosen.size || busy || jobRunning(jobId, job)} onClick={() => start("dry_run")}>Dry run</button>
            <button className="danger" disabled={!operator || !chosen.size || busy || jobRunning(jobId, job)} onClick={() => setConfirming(true)}>Execute...</button>
            {!operator && <span className="muted small">View only: ask an operator to run apply.</span>}
            {jobId && <JobLine state={job} label="Apply job" />}
            {jobId && !jobRunning(jobId, job) && <span className="muted small">See the run below for the result.</span>}
          </div>
          {err && <ErrorBox error={err} />}
          {confirming && (
            <Confirm word="EXECUTE" title="Execute" busy={busy} onCancel={() => setConfirming(false)} onConfirm={() => start("execute")}
                     body={<>
                       <p>Create these Unity Gateway model services (and the provider services they need) in <code>{meta.target_catalog}.{meta.target_schema}</code>:</p>
                       <ul className="small">{candidates.filter((p: any) => chosen.has(p.legacy_endpoint)).slice(0, 12).map((p: any) => <li key={p.legacy_endpoint}><code>{p.target_service}</code> from <code>{p.legacy_endpoint}</code></li>)}{chosen.size > 12 && <li>and {chosen.size - 12} more</li>}</ul>
                       <p className="small">Grants: <b>{grants ? "copied from legacy permissions" : "none"}</b>. Secrets: <b>{secretMode === "uc" ? "Unity Catalog secret references" : "values read from workspace secrets"}</b>. Legacy endpoints aren't changed. You can roll back from the history.</p>
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
  if (loading && !data) return <Loading text="Loading apply run" />;
  if (error?.startsWith("404")) return <Card title="Apply run"><Loading text="The apply job is starting; results appear here when it finishes" /><button className="ghost small" onClick={reload}>Reload</button></Card>;
  if (error) return <Card title="Apply run"><ErrorBox error={error} /><button className="ghost small" onClick={reload}>Reload</button></Card>;
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
  return (
    <Card title={`Apply run ${applyId.slice(0, 8)}`} actions={<><button className="ghost small" onClick={reload}>Reload</button>{canRollBack && <button className="danger small" onClick={() => setConfirming(true)}>Roll back...</button>}</>}
          note={`${m.mode.replace("_", " ")} by ${m.requested_by}, ${String(m.started_at).slice(0, 16)} UTC`}>
      <div><Badge value={m.status} /> {m.error && <ErrorBox error={m.error} />}</div>
      {rolledBack && <p className="small">Rolled back by run <button className="link" onClick={() => onOpen(rolledBack.apply_id)}>{String(rolledBack.apply_id).slice(0, 8)}</button> ({rolledBack.status}).</p>}
      {jobId && <JobLine state={job} label="Rollback" />}
      {err && <ErrorBox error={err} />}
      <Table rows={data.items} pageSize={50} empty={m.status === "RUNNING" ? "Running..." : "No results."} columns={[
        { key: "type", label: "Object", render: (i) => i.type?.replace(/_/g, " ") },
        { key: "name", label: "Name", render: (i) => <code className="wrap">{i.name}</code> },
        { key: "action", label: "Result", render: (i) => <Badge value={i.action} /> },
        { key: "reason", label: "Details", render: (i) => <span className="small">{i.reason || (i.issues || []).join("; ") || (i.grants ? i.grants.map((g: any) => `${g.principal}: ${g.privileges.join("+")}`).join(", ") : "")}</span> },
      ]} />
      {confirming && (
        <Confirm word="ROLLBACK" title="Roll back" busy={busy} onCancel={() => setConfirming(false)} onConfirm={rollback}
                 body={<>
                   <p>Delete the <b>{created}</b> object(s) this run created:</p>
                   <ul className="small">{data.items.filter((i: any) => i.action === "created").slice(0, 12).map((i: any) => <li key={i.type + i.name}><code>{i.name}</code> ({String(i.type).replace(/_/g, " ")})</li>)}</ul>
                   <p className="small">Objects that lost the toolkit's mark, or that another execute run still uses, are kept. Inference tables stay.</p>
                 </>} />
      )}
    </Card>
  );
}
