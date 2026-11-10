import { ReactNode, useEffect, useId, useMemo, useRef, useState } from "react";
import { ageDays, api, fmt, isUnknownId, jobRunning, JobState, kindLabel, plural, relativeAge, sentence, useApi, useJob, usePollWhileRunning } from "./api";
import { Badge, Card, Confirm, CopyButton, Elapsed, Empty, ErrorBox, ErrorState, ExportLink, JobLine, Notice, NavButton, PageHeader, Reason, Skeleton, SkeletonCard, SkeletonTable, Table, useRunView } from "./ui";
import type { WorkspaceSel } from "./App";

const NOT_READY = ["INCOMPLETE", "BLOCKED"];

export default function Apply({ scanRunId, setScanRunId, operator, active = true, workspace = null }: { scanRunId: string | null; setScanRunId: (id: string) => void; operator: boolean; active?: boolean; workspace?: WorkspaceSel }) {
  // Central mode: the scans, the history and every change follow the picked workspace (the job acts on the scan's).
  const wsQuery = workspace ? `?workspace_id=${encodeURIComponent(workspace.id)}` : "";
  const scans = useApi<any[]>(`/api/scans${wsQuery}`);
  const history = useApi<any[]>(`/api/applies${wsQuery}`);
  const config = useApi<any>("/api/config");
  // Tabs stay mounted, so a scan that finished on the Scans tab only shows up here after a reload on opening the tab.
  useEffect(() => { if (active) { scans.reload(); history.reload(); config.reload(); } }, [active]); // eslint-disable-line react-hooks/exhaustive-deps
  const maxAge: number = config.data?.max_scan_age_days ?? 14;
  const succeeded = (scans.data || []).filter((s) => s.status === "SUCCEEDED");
  const selectedScan = succeeded.find((s) => s.run_id === scanRunId);
  const runningApply = (history.data || []).find((a) => a.status === "RUNNING");
  const [openApply, setOpenApply] = useState<string | null>(null);
  const runView = useRunView<any>(history.data || [], (r) => r.apply_id === openApply);
  const [focusApply, setFocusApply] = useState(false);
  const [detailKey, setDetailKey] = useState(0);
  useEffect(() => {
    if (!scanRunId && succeeded.length) setScanRunId(succeeded[0].run_id);
  }, [scanRunId, succeeded.length]);
  // An apply run that is still going (started before a reload, or by someone else) opens its progress view.
  useEffect(() => {
    if (!openApply && runningApply) setOpenApply(runningApply.apply_id);
  }, [history.data]);
  const refresh = () => { history.reload(); setDetailKey((k) => k + 1); };
  const openRun = (id: string, focus = false) => { setOpenApply(id); setFocusApply(focus); };
  const listRow = (id: string | null) => (history.data || []).find((a) => a.apply_id === id);

  return (
    <div className="stack">
      <PageHeader title="Apply" description="Creates Unity Gateway provider services and model services for external model and Provisioned Throughput endpoints, plus grants if you choose them. Legacy endpoints are never changed. Databricks-hosted endpoints need nothing: their system AI services already exist." />
      <Card title="1. Choose a scan">
        {scans.loading && !scans.data ? <Skeleton lines={1} label="Loading scans" /> : scans.error ? <ErrorState error={scans.error} onRetry={scans.reload} /> : succeeded.length === 0 ? (
          <Empty title="No finished scans" action={<NavButton tab="scans" label="Go to Scans" />}>Run a workspace scan first; Apply uses its plan.</Empty>
        ) : (
          <div className="stack-sm">
            <label className="field" htmlFor="apply-scan">Scan</label>
            <select id="apply-scan" value={scanRunId || ""} onChange={(e) => setScanRunId(e.target.value)}>
              {succeeded.map((s) => <option key={s.run_id} value={s.run_id}>{String(s.finished_at || s.started_at).slice(0, 16)} UTC ({relativeAge(s.finished_at || s.started_at)}) · {s.workspace_url?.replace("https://", "")} · {String(s.readiness || "unknown").replace(/_/g, " ")}</option>)}
            </select>
            {selectedScan && (
              <div className="row small">
                <span>Readiness</span><Badge value={selectedScan.readiness || "unknown"} />
                <span className="muted">Scanned {relativeAge(selectedScan.finished_at || selectedScan.started_at)}</span>
              </div>
            )}
            {selectedScan && NOT_READY.includes(selectedScan.readiness) && (
              <Notice tone="warning" action={<NavButton tab="scans" label="Check on Scans" />}>
                This scan is {String(selectedScan.readiness).toLowerCase()}: {selectedScan.readiness === "BLOCKED" ? "enforcing would break something in this workspace" : "part of the scan failed, so readiness isn't decided"}. Check its results before you apply.
              </Notice>
            )}
          </div>
        )}
      </Card>
      {workspace && !workspace.hub && (
        <Notice tone="info" title={`Applying in ${workspace.label}`}>
          Central mode: the apply job signs in to <b>{workspace.label}</b> as the app's service principal and creates the services there. The scans and the history below are that workspace's.
        </Notice>
      )}
      {scanRunId && (
        <Planner key={scanRunId} wsLabel={workspace?.label || null} operator={operator} scanRunId={scanRunId} config={config.data} maxAge={maxAge} history={history.data || []}
                 runningApply={runningApply} onStarted={(id) => openRun(id, true)} onDone={refresh} />
      )}
      <Card title="History" actions={<button className="btn secondary sm" onClick={() => { if (!history.loading) history.reload(); }} aria-disabled={history.loading || undefined}>Reload</button>}>
        {history.loading && !history.data ? <SkeletonTable rows={3} label="Loading apply history" /> : history.error ? <ErrorState error={history.error} onRetry={history.reload} /> : (
          <div className="stack-sm">{runView.controls}
          <Table label="Apply history" rowKey={(r) => r.apply_id} rows={runView.shown} pageSize={runView.view === "all" ? 15 : 25} search={runView.view === "all"} rowCurrent={(r) => r.apply_id === openApply}
                 empty={<Empty title="No apply runs yet">Dry runs, executes and rollbacks appear here.</Empty>} columns={[
            { key: "started_at", label: "Started", render: (r) => <button className="btn link" onClick={() => openRun(r.apply_id)} aria-label={`Open ${r.mode.replace(/_/g, " ")} run from ${String(r.started_at).slice(0, 16)}`}>{String(r.started_at).slice(0, 16)}</button> },
            { key: "mode", label: "Mode", render: (r) => <Badge value={r.mode.replace(/_/g, " ")} tone={r.mode === "execute" ? "bad" : r.mode === "rollback" ? "warn" : "info"} /> },
            { key: "status", label: "Status", render: (r) => <>
              <Badge value={r.status} />{r.rolled_back && <div className="small muted">Rolled back</div>}</> },
            { key: "endpoints", label: "Endpoints", clamp: true, render: (r) => <span className="small">{r.mode === "rollback" || r.mode === "rollback_dry_run" ? `rollback of ${String(r.rollback_of).slice(0, 8)}` : String(r.endpoints || "").split(",").join(", ")}</span> },
            { key: "summary", label: "Result", sortable: false, clamp: true, render: (r) => <Summary s={r.summary} /> },
            ...(workspace ? [{ key: "workspace_id", label: "Workspace", hideOnPhone: true, render: (r: any) => <span className="small">{r.workspace_id || "-"}</span> }] : []),
            { key: "requested_by", label: "By" },
          ]} />
          </div>
        )}
      </Card>
      {openApply && <ApplyDetail key={`${openApply}-${detailKey}`} operator={operator} applyId={openApply} focus={focusApply}
                                 rolledBackInList={!!listRow(openApply)?.rolled_back} onClose={() => setOpenApply(null)}
                                 onRolledBack={refresh} onOpen={openRun} onFinished={history.reload} />}
    </div>
  );
}

function Summary({ s }: { s: string }) {
  let o: Record<string, number> = {};
  try { o = JSON.parse(s || "{}"); } catch { /* empty */ }
  const counts = Object.entries(o).filter(([k]) => k !== "not_carried_over" && k !== "kept_preexisting" && k !== "kept_other_run").map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`).join(", ") || "-";
  const notCarried = Number(o.not_carried_over) || 0;
  return <span className="small">{counts}{notCarried > 0 && <>. {plural(notCarried, "service")} {notCarried === 1 ? "doesn't" : "don't"} get all of the legacy endpoint's governance: see <b>Not carried over</b> in the details below.</>}</span>;
}

/** A result row's details: its reason or issues, the grants it lists, and what the new service doesn't get. */
function itemDetails(i: any): string {
  // Granted rows list what this run added (the prior grants stay as they were); kept rows list what stays.
  const list = Array.isArray(i.added) && i.action !== "kept" ? i.added : i.grants;
  const grants = Array.isArray(list) ? list.map((g: any) => `${g.principal}: ${(g.privileges || []).join("+")}`).join(", ") : "";
  const label = i.action === "kept" ? "Kept" : i.action === "granted" ? "Granted" : i.action === "would_grant" ? "Would grant" : "";
  const parts = [i.reason || (i.issues || []).join("; "), grants && (label ? `${label}: ${grants}` : grants)];
  if (Array.isArray(i.not_carried_over) && i.not_carried_over.length) parts.push(`Not carried over: ${i.not_carried_over.join(", ")}`);
  return parts.filter(Boolean).join("; ");
}

const sortedObject = (o: Record<string, string>) => Object.fromEntries(Object.entries(o).sort(([a], [b]) => a.localeCompare(b)));
/** The plan's plain-words consequence of losing an endpoint's guardrails ("This endpoint blocks requests that
 *  contain PII today ... The new service won't: ..."), without the suggested service policies. */
const guardrailConsequence = (p: any): string | null => {
  const n = (Array.isArray(p.needs_human) ? p.needs_human : []).map((x: string) => String(x).replace(/^BLOCKS APPLY: /, ""))
    .find((x: string) => x.startsWith("guardrails"));
  if (!n) return null;
  const text = n.includes(":") ? n.slice(n.indexOf(":") + 1) : n;
  return text.split(" Suggested:")[0].trim();
};
const hasGuardrails = (p: any) => (Array.isArray(p.needs_human) ? p.needs_human : []).some((n: string) => String(n).replace(/^BLOCKS APPLY: /, "").startsWith("guardrails"));

/** Unity Catalog name check for one secret: catalog.schema.name, in an allowed schema when the installer set a list. */
function secretError(v: string, allowed: string[]): string | null {
  if (v.includes("<")) return "Replace the placeholder with your Unity Catalog secret name.";
  if (!/^[^.\s]+\.[^.\s]+\.[^.\s]+$/.test(v)) return "Use three parts: catalog.schema.name.";
  const schema = v.split(".").slice(0, 2).join(".");
  if (allowed.length && !allowed.includes(schema.toLowerCase())) return `${schema} isn't an allowed schema. Allowed: ${allowed.join(", ")}.`;
  return null;
}

const DEFAULT_TARGET = ["ai_gateway", "migrated"];
const NAME_RE = /^[A-Za-z0-9_-]{1,255}$/;

/** value, once it has stopped changing for ms (so typing a schema name doesn't query on every key). */
function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  const key = JSON.stringify(value);
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t); }, [key, ms]); // eslint-disable-line react-hooks/exhaustive-deps
  return v;
}

function TargetField({ label, value, onChange, disabled }: { label: string; value: string; onChange: (v: string) => void; disabled: boolean }) {
  const id = useId();
  const bad = !!value && !NAME_RE.test(value);
  return (
    <div className="field-group">
      <label className="field" htmlFor={id}>{label}</label>
      <input id={id} value={value} disabled={disabled} spellCheck={false} onChange={(e) => onChange(e.target.value)}
             aria-invalid={bad || !value} aria-describedby={bad ? `${id}-error` : undefined} />
      {bad && <span id={`${id}-error`} className="field-error">Use letters, digits, _ and -.</span>}
    </div>
  );
}

/** Default Unity Catalog secret name for a workspace secret: scope_key, lower case, [a-z0-9_] only (the job's rule). */
export const ucSecretLeaf = (scopeKey: string) =>
  (scopeKey.toLowerCase().replace("/", "_").replace(/[^a-z0-9_]+/g, "_").replace(/^_+|_+$/g, "") || "secret").slice(0, 255);

function SecretRow({ secret, value, error, disabled, onChange, label, hint }: {
  secret: string; value: string; error: string | null; disabled: boolean; onChange: (v: string) => void;
  label?: string; hint?: ReactNode;
}) {
  const id = useId();
  return (
    <div className="secret-row">
      <div className="field-group">
        <label className="field" htmlFor={id}>{label || "Unity Catalog secret for workspace secret"} <code className="wrap">{secret}</code></label>
        <input id={id} value={value} disabled={disabled} spellCheck={false} onChange={(e) => onChange(e.target.value)}
               aria-invalid={!!error} aria-describedby={error ? `${id}-hint ${id}-error` : `${id}-hint`} />
        <span id={`${id}-hint`} className="small muted">{hint || "Format catalog.schema.name"}</span>
        {error && <span id={`${id}-error`} className="field-error">{error}</span>}
      </div>
    </div>
  );
}

function Planner({ scanRunId, onStarted, onDone, operator, config, maxAge, history, runningApply, wsLabel = null }: {
  scanRunId: string; onStarted: (id: string) => void; onDone: () => void; operator: boolean; config: any; maxAge: number;
  history: any[]; runningApply: any; wsLabel?: string | null;
}) {
  const { data, error, loading, reload } = useApi<any>(`/api/scans/${scanRunId}`);
  const meta: any = data?.meta;
  // The target is chosen here, not in the scan: prefilled from the scan (or the default), changeable without a new scan.
  const [tCat, setTCat] = useState("");
  const [tSch, setTSch] = useState("");
  useEffect(() => {
    if (!meta) return;
    setTCat(meta.target_catalog || DEFAULT_TARGET[0]);
    setTSch(meta.target_schema || DEFAULT_TARGET[1]);
  }, [meta?.run_id]); // eslint-disable-line react-hooks/exhaustive-deps
  const targetOk = NAME_RE.test(tCat) && NAME_RE.test(tSch);
  const [checkCat, checkSch] = useDebounced([tCat, tSch], 500);
  const schemaPath = meta && NAME_RE.test(checkCat) && NAME_RE.test(checkSch)
    ? `/api/target-schema?catalog=${encodeURIComponent(checkCat)}&schema=${encodeURIComponent(checkSch)}` : null;
  const schema = useApi<any>(schemaPath);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [secretMode, setSecretMode] = useState<"uc" | "create" | "read">("uc");
  const [names, setNames] = useState<Record<string, string>>({});
  const [createNames, setCreateNames] = useState<Record<string, string>>({});
  const [createSchema, setCreateSchema] = useState<string>("");
  const [grants, setGrants] = useState(false);
  const [ack, setAck] = useState(false);
  const [allowStale, setAllowStale] = useState(false);
  const [smokeTest, setSmokeTest] = useState(true);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [conflict, setConflict] = useState<{ run: any | null; job: { job_run_id: string; url: string | null } | null } | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [lastMode, setLastMode] = useState<"dry_run" | "execute">("dry_run");
  // The last dry run that succeeded, with the selection it was run for. Execute needs one that matches.
  const [dry, setDry] = useState<{ applyId: string; sig: string } | null>(null);
  // A dry run that ended NEEDS_ATTENTION: the endpoints whose rows need a person (manual, skipped or error).
  const [attention, setAttention] = useState<{ sig: string; endpoints: string[] } | null>(null);
  const pending = useRef<{ applyId: string; sig: string; mode: string } | null>(null);
  const candidates = useMemo(() => (data?.plan || []).filter((p: any) => p.action === "create_model_service"), [data]);
  const secrets: string[] = useMemo(() => {
    const all: string[] = (data?.providers || []).flatMap((p: any) => (Array.isArray(p.secrets) ? p.secrets : []));
    return Array.from(new Set(all));
  }, [data]);
  const allowedSchemas: string[] = (config?.secret_schemas || []).map((s: string) => s.toLowerCase());
  const copyAllowed = !!config?.allow_secret_read;
  const target = `${tCat}.${tSch}`;
  const scanTarget = `${meta?.target_catalog || ""}.${meta?.target_schema || ""}`;
  // The plan names its services in the scan's target; show them in the target chosen here (system.ai stays as is).
  const retarget = (fqn: string) => (fqn && scanTarget !== "." && fqn.toLowerCase().startsWith(scanTarget.toLowerCase() + ".")
    ? `${target}${fqn.slice(scanTarget.length)}` : fqn);
  const sameTarget = target.toLowerCase() === scanTarget.toLowerCase();
  const mappingOff = secrets.length > 0 && allowedSchemas.length === 0;

  // Default name per secret: the target schema when the installer allowed it, else the first allowed schema.
  const defaultName = (secret: string) => {
    const schemaName = allowedSchemas.includes(target.toLowerCase()) ? target : allowedSchemas[0] || "<catalog>.<schema>";
    return `${schemaName}.${secret.split("/").pop()!.replace(/[^A-Za-z0-9_-]/g, "_")}`;
  };
  // Create mode: the job writes each Unity Catalog secret in one allowed schema (the target when it's allowed).
  const createIn = createSchema && allowedSchemas.includes(createSchema) ? createSchema
    : allowedSchemas.includes(target.toLowerCase()) ? target.toLowerCase() : allowedSchemas[0] || "";
  const createNameFor = (s: string) => createNames[s] ?? `${createIn}.${ucSecretLeaf(s)}`;
  const nameFor = (s: string) => (secretMode === "create" ? createNameFor(s) : names[s] ?? defaultName(s));
  const secretErrors: Record<string, string> = {};
  if (secretMode !== "read" && !mappingOff) secrets.forEach((s) => { const e = secretError(nameFor(s), allowedSchemas); if (e) secretErrors[s] = e; });
  const secretErrorCount = Object.keys(secretErrors).length;
  const ucMapping = Object.fromEntries(secrets.map((s) => [s, `secrets/${nameFor(s)}`]));

  // Which endpoints earlier execute runs of this scan already created (and no rollback undid).
  const createdBy: Record<string, string> = {};
  history.filter((a) => a.mode === "execute" && a.scan_run_id === scanRunId && ["SUCCEEDED", "NEEDS_ATTENTION"].includes(a.status))
    .forEach((a) => {
      const undone = !!a.rolled_back || history.some((r) => r.mode === "rollback" && r.rollback_of === a.apply_id && ["SUCCEEDED", "RUNNING"].includes(r.status));
      if (!undone) String(a.endpoints || "").split(",").filter(Boolean).forEach((e) => { createdBy[e] = a.apply_id; });
    });

  const sig = JSON.stringify({ e: Array.from(chosen).sort(), t: target.toLowerCase(), m: sortedObject(secretMode !== "read" ? ucMapping : {}), r: secretMode === "read", c: secretMode === "create", g: grants, a: ack });
  const sigRef = useRef(sig);
  sigRef.current = sig;
  const job = useJob(jobId, (s: JobState) => {
    const p = pending.current;
    pending.current = null;
    onDone();
    if (p?.mode === "dry_run" && s.result === "SUCCESS") {
      api<any>(`/api/applies/${p.applyId}`).then((d) => {
        if (d.meta?.status === "SUCCEEDED") { setDry({ applyId: p.applyId, sig: p.sig }); setAttention(null); return; }
        if (d.meta?.status !== "NEEDS_ATTENTION") return;
        // Map each model service row that needs a person back to its legacy endpoint, through the names shown here.
        const byService: Record<string, string> = {};
        candidates.forEach((c: any) => { byService[String(retarget(c.target_service)).toLowerCase()] = c.legacy_endpoint; });
        const blocked = new Set<string>();
        (d.items || []).forEach((i: any) => {
          if (i.type === "model_service" && ["manual", "skipped", "error"].includes(i.action)) {
            const ep = byService[String(i.name || "").toLowerCase()];
            if (ep) blocked.add(ep);
          }
        });
        setAttention({ sig: p.sig, endpoints: Array.from(blocked).sort() });
      }).catch(() => { /* the dry run stays unconfirmed */ });
    }
  });
  // Reload during a dry run or execute: resume its progress. Its result counts for the selection shown now (the server checks it again).
  useEffect(() => {
    if (!runningApply || jobId || runningApply.scan_run_id !== scanRunId || String(runningApply.mode).startsWith("rollback")) return;
    setJobId(runningApply.job_run_id);
    setLastMode(runningApply.mode);
    pending.current = { applyId: runningApply.apply_id, sig: sigRef.current, mode: runningApply.mode };
  }, [runningApply?.apply_id]);

  if (loading && !data) return <SkeletonCard title="2. Choose endpoints and options" />;
  if (error) return <Card title="2. Choose endpoints and options"><ErrorState error={error} onRetry={reload} title="Couldn't load the plan" /></Card>;
  const running = jobRunning(jobId, job) || !!runningApply;
  const ageNow = ageDays(meta.finished_at);
  const stale = ageNow !== null && ageNow > maxAge;
  const staleBlocked = stale && !allowStale;
  const schemaMissing = !!schema.data && schema.data.exists === false;
  const schemaNoGrant = !!schema.data && schema.data.exists !== false && schema.data.can_create_service === false;
  const needsAck = candidates.some((p: any) => chosen.has(p.legacy_endpoint) && hasGuardrails(p));
  const dryOk = !!dry && dry.sig === sig;
  const schemaSql = [
    ...(schemaMissing ? [`CREATE SCHEMA IF NOT EXISTS \`${tCat}\`.\`${tSch}\`;`] : []),
    `GRANT CREATE SERVICE ON SCHEMA \`${tCat}\`.\`${tSch}\` TO \`<installer identity or you>\`;`,
  ].join("\n");
  const baseReasons = [
    !operator && "Only operators can start apply runs.",
    !chosen.size && "Select at least one endpoint.",
    !targetOk && "Enter the target catalog and schema (letters, digits, _ and -).",
    targetOk && (checkCat !== tCat || checkSch !== tSch) && "Checking the target schema.",
    running && "Another apply run is in progress.",
    schema.loading && !schema.data && "Checking the target schema.",
    schemaMissing && `The target schema ${target} doesn't exist yet (see the notice above).`,
    schemaNoGrant && "The jobs' identity needs CREATE SERVICE on the target schema (see the notice above).",
    mappingOff && secretMode !== "read" && "Secret mapping is off (see Provider API keys).",
    secretErrorCount > 0 && `Fix ${plural(secretErrorCount, "Unity Catalog secret name")} under Provider API keys.`,
    staleBlocked && "This scan is too old: tick “Apply with this older scan anyway” to continue, or scan again.",
  ].filter(Boolean) as string[];
  const dryReasons = baseReasons;
  const execReasons = [
    ...baseReasons,
    needsAck && !ack && "Tick the guardrails acknowledgement first.",
    !dryOk && (attention && attention.sig === sig
      ? (attention.endpoints.length
        ? `The dry run needs a person for ${attention.endpoints.length === 1 ? "1 endpoint" : `${attention.endpoints.length} endpoints`} (${attention.endpoints.join(", ")}): see the rows marked manual below. Deselect ${attention.endpoints.length === 1 ? "it" : "them"} or fix ${attention.endpoints.length === 1 ? "it" : "them"}, then dry run again.`
        : "The dry run needs attention: check the rows marked manual, error or kept below, fix them, then dry run again.")
      : "Run a dry run with this selection first."),
  ].filter(Boolean) as string[];
  const dryDisabled = dryReasons.length > 0 || busy;
  const execDisabled = execReasons.length > 0 || busy;

  const start = async (mode: "dry_run" | "execute") => {
    if (mode === "execute" ? execDisabled : dryDisabled) return;
    setErr(null);
    setConflict(null);
    setBusy(true);
    try {
      const r: any = await api("/api/applies", { method: "POST", body: JSON.stringify({
        mode, scan_run_id: scanRunId, endpoints: Array.from(chosen), target_catalog: tCat,
        target_schema: tSch, uc_secret_map: secretMode !== "read" ? ucMapping : {},
        allow_secret_read: secretMode === "read", create_uc_secrets: secretMode === "create", grants, ack_guardrails: ack, allow_stale: allowStale,
        smoke_test: mode === "execute" && smokeTest,
        dry_run_id: mode === "execute" ? dry?.applyId || "" : "", confirm: mode === "execute" ? "EXECUTE" : "" }) });
      pending.current = { applyId: r.apply_id, sig, mode };
      setLastMode(mode);
      setJobId(r.job_run_id);
      onStarted(r.apply_id);
    } catch (e: any) {
      if (e.status === 409 && e.job) {
        // Another run holds the slot: link to it instead of repeating the error. Other 409s (a dry run that changed
        // or expired, a stale scan) are errors with their own reason.
        const run = await api<any[]>("/api/applies").then((rows) => rows.find((a) => a.status === "RUNNING") || null).catch(() => null);
        setConflict({ run, job: e.job ?? null });
      } else {
        setErr(e.message);
      }
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  };

  const openConflict = (a: any) => {
    setJobId(a.job_run_id);
    setLastMode(a.mode === "execute" ? "execute" : "dry_run");
    pending.current = null;
    setConflict(null);
    setErr(null);
    onStarted(a.apply_id);
  };

  return (
    <Card title="2. Choose endpoints and options" note={<>Scan readiness: <Badge value={data.readiness?.status || "unknown"} /> · scanned {relativeAge(meta.finished_at)}.</>}>
      {candidates.length === 0 ? <Empty title="Nothing to create">Nothing in this scan can be created automatically. Apply creates model services for external model endpoints (OpenAI, Anthropic, Azure OpenAI, or a databricks-* endpoint behind the databricks-model-serving provider) and Provisioned Throughput endpoints. Endpoints marked Manual in the plan list their steps in the notes.</Empty> : (
        <>
          <fieldset className="panel">
            <legend>Target schema for the new services</legend>
            <div className="row">
              <TargetField label="Target catalog" value={tCat} onChange={(v) => setTCat(v.trim())} disabled={!operator} />
              <TargetField label="Target schema" value={tSch} onChange={(v) => setTSch(v.trim())} disabled={!operator} />
            </div>
            <p className="small muted">
              The schema must exist, and the jobs' identity needs <code>CREATE SERVICE</code> on it. Change it here without
              scanning again{meta.target_catalog && !sameTarget ? <> (the scan proposed <code>{scanTarget}</code>)</> : null}.
            </p>
          </fieldset>
          {schema.error && <ErrorBox error={schema.error} title="Couldn't check the target schema" />}
          {schema.data?.error && <Notice tone="warning" title="Couldn't check the target schema">{schema.data.error} The apply job checks it again when it runs.</Notice>}
          {(schemaMissing || schemaNoGrant) && (
            <Notice tone="error" title={schemaMissing ? `The target schema ${target} doesn't exist` : `The jobs' identity can't create services in ${target}`}>
              <p>{schemaMissing ? "Create it, then grant CREATE SERVICE on it. Run this in a SQL editor, as the schema owner or an admin:" : "Grant CREATE SERVICE on it. Run this in a SQL editor, as the schema owner or an admin:"}</p>
              <pre className="sql">{schemaSql}</pre>
              <div className="row"><CopyButton text={schemaSql} label="Copy SQL" /></div>
              <p className="small">Dry run and execute stay off until the schema is ready.</p>
            </Notice>
          )}
          {stale && (
            <>
              <Notice tone="warning" title={`This scan is ${relativeAge(meta.finished_at)} old`} action={<NavButton tab="scans" label="Go to Scans to scan again" />}>
                Endpoints, callers and code may have changed since. Scan again first, or apply with this scan anyway (checkbox below).
              </Notice>
              <label className="choice"><input type="checkbox" checked={allowStale} onChange={(e) => setAllowStale(e.target.checked)} /> <span>Apply with this older scan anyway</span></label>
            </>
          )}
          <Table label="Endpoints apply can migrate" rows={candidates} pageSize={50} tools={<>
            <span className="small muted" aria-live="polite">{chosen.size} of {candidates.length} selected</span>
            <button className="btn secondary sm" onClick={() => { if (chosen.size < candidates.length) setChosen(new Set(candidates.map((p: any) => p.legacy_endpoint))); }}
                    aria-disabled={chosen.size === candidates.length || undefined}>Select all</button>
            <button className="btn secondary sm" onClick={() => { if (chosen.size) setChosen(new Set()); }} aria-disabled={!chosen.size || undefined}>Clear</button>
          </>} columns={[
            { key: "pick", label: "Select", width: "36px", sortable: false, render: (p) => <input type="checkbox" aria-label={`Select ${p.legacy_endpoint}`} checked={chosen.has(p.legacy_endpoint)} onChange={(e) => { const s = new Set(chosen); e.target.checked ? s.add(p.legacy_endpoint) : s.delete(p.legacy_endpoint); setChosen(s); }} /> },
            { key: "legacy_endpoint", label: "Legacy endpoint", render: (p) => <code>{p.legacy_endpoint}</code> },
            { key: "kind", label: "Kind", render: (p) => kindLabel(p.kind) },
            { key: "target_service", label: "Creates", render: (p) => <>
              <code>{retarget(p.target_service)}</code> {sameTarget && p.target_status === "exists" && <Badge value="exists" tone="good" />}
              {createdBy[p.legacy_endpoint] && <div><Badge value={`created by run ${createdBy[p.legacy_endpoint].slice(0, 8)}`} tone="info" /></div>}
            </> },
            { key: "requests_window", label: "Requests", num: true, render: (p) => fmt(p.requests_window) },
            { key: "needs_human", label: "Notes", sortable: false, render: (p) => (Array.isArray(p.needs_human) ? p.needs_human : []).map((n: string, i: number) => {
              const blocks = String(n).startsWith("BLOCKS APPLY: ");
              const text = sentence(String(n).replace(/^BLOCKS APPLY: /, ""));
              return <div key={i} className="small">{blocks && <><Badge value="Blocks apply" tone="bad" /> </>}{text}</div>;
            }) },
          ]} />
          <div className="panel">
            <fieldset>
              <legend>Provider API keys</legend>
              <label className="choice"><input type="radio" name="secret-mode" checked={secretMode === "uc"} onChange={() => setSecretMode("uc")} /> <span>Reference Unity Catalog secrets (recommended)</span></label>
              {secretMode === "uc" && (
                <div className="stack-sm secret-map">
                  {mappingOff ? (
                    <Notice tone="warning" title="Secret mapping is off">
                      The installer didn't allow any Unity Catalog secret schema, so this app can't map the keys. Re-run the installer (Install) with Allowed secret schemas set, then reload this page.
                    </Notice>
                  ) : secrets.length === 0 ? (
                    <p className="small muted">The provider services in this plan need no API keys.</p>
                  ) : (<>
                    <p className="small muted">Create the Unity Catalog secrets first, then name each one here. Allowed schemas: {allowedSchemas.length ? <code>{allowedSchemas.join(", ")}</code> : "none"}.</p>
                    {secrets.map((s) => (
                      <SecretRow key={s} secret={s} value={nameFor(s)} error={secretErrors[s] || null} disabled={false}
                                 hint={<>An existing Unity Catalog secret that holds this key (not the target schema). Allowed schemas: {allowedSchemas.length ? <code>{allowedSchemas.join(", ")}</code> : "none"}.</>}
                                 onChange={(v) => setNames({ ...names, [s]: v })} />
                    ))}
                  </>)}
                </div>
              )}
              <label className="choice"><input type="radio" name="secret-mode" checked={secretMode === "create"} disabled={allowedSchemas.length === 0}
                     aria-describedby={allowedSchemas.length ? undefined : "secret-create-reason"} onChange={() => setSecretMode("create")} /> <span>Create Unity Catalog secrets from the workspace secrets</span></label>
              {allowedSchemas.length === 0 && <p id="secret-create-reason" className="small muted reason">Not available: the installer didn't allow a Unity Catalog secret schema. Re-run the installer with Advanced: Allowed secret schemas set.</p>}
              {secretMode === "create" && allowedSchemas.length > 0 && (
                <div className="stack-sm secret-map">
                  <p className="small muted">The apply job reads each workspace secret with its own identity and stores the value in a new Unity Catalog secret, which the provider service then references. Values are never shown or logged. The dry run checks that each workspace secret can be read; rollback deletes the secrets that run created.</p>
                  {secrets.length === 0 ? <p className="small muted">The provider services in this plan need no API keys.</p> : (<>
                    <div className="field-group">
                      <label className="field" htmlFor="create-secret-schema">Schema for the new secrets</label>
                      <select id="create-secret-schema" value={createIn} onChange={(e) => { setCreateSchema(e.target.value); setCreateNames({}); }}>
                        {allowedSchemas.map((s) => <option key={s} value={s}>{s}</option>)}
                      </select>
                    </div>
                    {secrets.map((s) => (
                      <SecretRow key={s} secret={s} value={createNameFor(s)} error={secretErrors[s] || null} disabled={false}
                                 label="New Unity Catalog secret for workspace secret"
                                 hint="Created by the apply job (catalog.schema.name). If it already exists, it's reused as is."
                                 onChange={(v) => setCreateNames({ ...createNames, [s]: v })} />
                    ))}
                  </>)}
                </div>
              )}
              <label className="choice"><input type="radio" name="secret-mode" checked={secretMode === "read"} disabled={!copyAllowed} aria-describedby={copyAllowed ? undefined : "secret-read-reason"} onChange={() => setSecretMode("read")} /> <span>Copy the workspace secret values into the provider service</span></label>
              {!copyAllowed && <p id="secret-read-reason" className="small muted reason">Not available: copying key values is turned off for this app. Use Unity Catalog secrets.</p>}
              {secretMode === "read" && copyAllowed && <Notice tone="warning">The key is then stored in the provider service, and the identity that runs the apply job reads it (even if you can't). Prefer Unity Catalog secrets.</Notice>}
            </fieldset>
            <label className="choice"><input type="checkbox" checked={grants} onChange={(e) => setGrants(e.target.checked)} /> <span>Copy legacy endpoint permissions as EXECUTE / MANAGE grants</span></label>
          </div>
          {needsAck && (
            <div className="panel">
              <Notice tone="warning" title="The new services won't have these endpoints' guardrails">
                <ul className="small">
                  {candidates.filter((p: any) => chosen.has(p.legacy_endpoint) && hasGuardrails(p)).map((p: any) => (
                    <li key={p.legacy_endpoint}><code>{p.legacy_endpoint}</code>: {guardrailConsequence(p)}</li>
                  ))}
                </ul>
                After apply, <b>Verify &amp; cut over &gt; Guardrail check</b> compares the legacy endpoint and the new service with a harmless probe.
              </Notice>
              <label className="choice"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> <span>I understand that requests these guardrails block today will reach the model through the new services, until I re-create the protection</span></label>
            </div>
          )}
          <div className="row">
            <button className="btn" onClick={() => { if (!dryDisabled) start("dry_run"); }} aria-disabled={dryDisabled || undefined}
                    aria-describedby={dryReasons.length ? "apply-dry-reason" : undefined}>{busy && lastMode === "dry_run" ? "Starting…" : "Dry run"}</button>
            <button className="btn danger" onClick={() => { if (!execDisabled) setConfirming(true); }} aria-disabled={execDisabled || undefined}
                    aria-describedby={execReasons.length ? "apply-exec-reason" : undefined}>Execute…</button>
          </div>
          {dryReasons.length > 0 && <Reason id="apply-dry-reason">Dry run is unavailable. {dryReasons.join(" ")}</Reason>}
          {execReasons.length > 0 && <Reason id="apply-exec-reason">Execute is unavailable. {execReasons.join(" ")}</Reason>}
          {!dryOk && attention && attention.sig === sig && attention.endpoints.length > 0 && operator && (
            <button className="btn secondary sm" onClick={() => {
              const next = new Set(chosen);
              attention.endpoints.forEach((e) => next.delete(e));
              setChosen(next);
            }}>Deselect {attention.endpoints.length === 1 ? "it" : `these ${attention.endpoints.length}`}</button>
          )}
          {dry && dry.sig === sig && <p className="small">Dry run checked. Execute does exactly what it showed.</p>}
          {jobId && <JobLine state={job} label={lastMode === "execute" ? "Execute" : "Dry run"} done="See the run below for every object." />}
          {err && <ErrorBox error={err} title={lastMode === "execute" ? "Couldn't start the execute" : "Couldn't start the dry run"} />}
          {conflict && (
            <Notice tone="info" action={<>
              {conflict.run && <button className="btn secondary sm" onClick={() => openConflict(conflict.run)}>Open the running apply</button>}
              {conflict.job?.url && <a className="btn link sm" href={conflict.job.url} target="_blank" rel="noreferrer">View job run</a>}
            </>}>
              {conflict.run
                ? `${conflict.run.mode === "execute" ? "An execute" : conflict.run.mode === "rollback" ? "A rollback" : conflict.run.mode === "rollback_dry_run" ? "A rollback dry run" : "A dry run"} is already running, started ${relativeAge(conflict.run.started_at)} by ${conflict.run.requested_by}.`
                : "Another apply run is already running."}
            </Notice>
          )}
          {confirming && (
            <Confirm word="EXECUTE" title="Execute" action={`Create ${plural(chosen.size, "service")}`} busy={busy}
                     onCancel={() => setConfirming(false)} onConfirm={() => start("execute")}
                     body={<>
                       {wsLabel && <p>In workspace <b>{wsLabel}</b>.</p>}
                       <p>Create these model services (and the provider services they need) in <code>{target}</code>:</p>
                       <ul className="small">{candidates.filter((p: any) => chosen.has(p.legacy_endpoint)).slice(0, 12).map((p: any) => <li key={p.legacy_endpoint}><code>{retarget(p.target_service)}</code> from <code>{p.legacy_endpoint}</code></li>)}{chosen.size > 12 && <li>and {chosen.size - 12} more</li>}</ul>
                       <p className="small">Grants: <b>{grants ? "copied from legacy permissions" : "none"}</b>. Keys: <b>{secretMode === "uc" ? "Unity Catalog secret references" : secretMode === "create" ? "new Unity Catalog secrets created from the workspace secrets" : "copied from workspace secrets"}</b>.</p>
                       {needsAck && (
                         <Notice tone="warning" title="Guardrails don't carry over">
                           <ul className="small">
                             {candidates.filter((p: any) => chosen.has(p.legacy_endpoint) && hasGuardrails(p)).map((p: any) => (
                               <li key={p.legacy_endpoint}><code>{p.legacy_endpoint}</code>: {guardrailConsequence(p)}</li>
                             ))}
                           </ul>
                         </Notice>
                       )}
                       <label className="choice"><input type="checkbox" checked={smokeTest} onChange={(e) => setSmokeTest(e.target.checked)} /> <span>Check the new services after creating them</span></label>
                       <Notice tone="warning" title="Rolling back later">
                         You can roll back from the history: it deletes the objects this run created (objects another run still uses are kept).
                         If callers have already moved to the new Unity Gateway endpoints, rolling back breaks their traffic.
                       </Notice>
                     </>} />
          )}
        </>
      )}
    </Card>
  );
}

function ApplyDetail({ applyId, onRolledBack, onOpen, onFinished, onClose, operator, focus, rolledBackInList }: {
  applyId: string; onRolledBack: () => void; onOpen: (id: string, focus?: boolean) => void; onFinished: () => void; onClose: () => void;
  operator: boolean; focus: boolean; rolledBackInList: boolean;
}) {
  const { data, error, loading, reload } = useApi<any>(`/api/applies/${applyId}`);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  // A new run takes focus on its heading so screen reader and keyboard users land on its progress.
  useEffect(() => { if (focus) heading.current?.focus(); }, []);
  const job = useJob(jobId, onRolledBack);
  usePollWhileRunning(data?.meta?.status, error, reload, onFinished);
  const title = `Apply run ${applyId.slice(0, 8)}`;
  if (isUnknownId(error)) {
    return (
      <Card title="Run not found" headingRef={heading}>
        <Notice tone="warning" title="This apply run doesn't exist">It may have been removed, or the link is out of date.</Notice>
        <div className="row"><button className="btn secondary sm" onClick={onClose}>Back to history</button></div>
      </Card>
    );
  }
  const inProgress = data?.meta?.status === "RUNNING" || data?.meta?.status === "STARTING";
  if (inProgress) {
    return (
      <Card title={title} headingRef={heading} note={data?.meta?.started_at ? <>Started {String(data.meta.started_at).slice(0, 16)} UTC · <Elapsed since={data.meta.started_at} /></> : undefined}>
        <Notice tone="info">{data?.meta?.status === "STARTING" ? "Starting the apply run. This page checks automatically." : "The job is running. Results appear here when it finishes; this page checks automatically."}</Notice>
        <SkeletonTable rows={3} label="Waiting for apply results" />
      </Card>
    );
  }
  if (loading && !data) return <Card title={title} headingRef={heading}><Skeleton lines={3} label="Loading apply run" /></Card>;
  if (error) return <Card title={title} headingRef={heading}><ErrorState error={error} onRetry={reload} title="Couldn't load this run" /></Card>;
  const m = data.meta;
  const created = data.items.filter((i: any) => i.action === "created").length;
  // A rollback first runs as a dry run (what it would delete); its results page offers the rollback itself.
  const toDelete = data.items.filter((i: any) => i.action === "would_delete");
  const rollbackDry = m.mode === "rollback_dry_run";
  const rollbacks: any[] = data.rollbacks || [];
  const rolledBack = rollbacks.find((r) => r.status === "SUCCEEDED" || r.status === "RUNNING");
  const alreadyRolledBack = !!rolledBack || rolledBackInList;
  const rollbackOffered = operator && m.mode === "execute" && created > 0 && ["SUCCEEDED", "NEEDS_ATTENTION", "FAILED"].includes(m.status);
  // A rollback dry run that keeps some objects finishes as NEEDS_ATTENTION ("kept" is a problem action): it still
  // unlocks the rollback of what it would delete. One with other problems (an object it couldn't read, so the
  // rollback might delete something it didn't list) doesn't: the server says why (unlock_problem).
  const unlockProblem: string | null = rollbackDry ? (m.unlock_problem || null) : null;
  const rollbackDryDone = rollbackDry && ["SUCCEEDED", "NEEDS_ATTENTION"].includes(m.status) && !unlockProblem;
  // Each rollback dry run unlocks one rollback: once a rollback used it, link to that run instead of the button.
  const usedBy: string | null = rollbackDry ? (m.used_by || null) : null;
  const deleteOffered = operator && rollbackDryDone && toDelete.length > 0 && !usedBy;
  // Nothing left to delete (gone, kept for another run, or older than the run): the rollback still has to run once to
  // record it, or the execute run stays "not rolled back" (and uninstall keeps it pending).
  const recordOffered = operator && rollbackDryDone && toDelete.length === 0 && !usedBy;
  const rollbackReason = alreadyRolledBack ? "This run was already rolled back." : jobRunning(jobId, job) ? "A rollback is already running." : null;
  const startRollback = async (body: Record<string, string>) => {
    setBusy(true);
    setErr(null);
    try {
      const r: any = await api("/api/applies", { method: "POST", body: JSON.stringify(body) });
      setJobId(r.job_run_id);
      onOpen(r.apply_id, true);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  };
  const rollbackDryRun = () => { if (!rollbackReason) startRollback({ mode: "rollback_dry_run", rollback_of: applyId }); };
  const rollback = () => startRollback({ mode: "rollback", rollback_of: String(m.rollback_of), dry_run_id: applyId, confirm: "ROLLBACK" });
  const outcome = {
    SUCCEEDED: <Notice tone="success" title={`${m.mode === "dry_run" ? "Dry run" : m.mode === "rollback" ? "Rollback" : rollbackDry ? "Rollback dry run" : "Execute"} succeeded`}><Summary s={m.summary} /></Notice>,
    NEEDS_ATTENTION: <Notice tone="warning" title="Finished with items that need attention">Check the rows marked manual, error, mismatch or kept below. <Summary s={m.summary} /></Notice>,
    FAILED: <Notice tone="error" title="Run failed">{m.error || "The job ended without recording a result."}</Notice>,
  }[m.status as string];
  const next = rollbackDryDone && usedBy
    ? <>A rollback already used this dry run: <button className="btn link" onClick={() => onOpen(usedBy)}>{usedBy.slice(0, 8)}</button>. To roll back again, run a new rollback dry run from the execute run.</>
    : rollbackDryDone
    ? (toDelete.length ? "Check what rollback would delete below. If it's right, delete them: that runs the rollback of the same execute run."
      : "Rollback would delete nothing: the objects are gone, changed or still used by another run (see below). Record the rollback so this execute run counts as rolled back where that applies.")
    : m.mode === "dry_run" && m.status === "SUCCEEDED"
    ? "If the plan looks right, execute the same selection. Execute creates the objects, and you can roll back from this history."
    : m.mode === "execute" && ["SUCCEEDED", "NEEDS_ATTENTION"].includes(m.status)
      ? <>Move callers to the new Unity Gateway endpoints, then scan again to confirm readiness. <NavButton tab="scans" label="Go to Scans" /></>
      : null;
  return (
    <Card title={title} headingRef={heading} note={`${m.mode.replace(/_/g, " ")} by ${m.requested_by} · ${String(m.started_at).slice(0, 16)} UTC`}
          actions={<>
            <ExportLink href={`/api/applies/${applyId}/export`} label="Export results (CSV)" />
            {rollbackOffered && (
              <button className="btn secondary sm" aria-disabled={!!rollbackReason || busy || undefined} aria-describedby={rollbackReason ? "rollback-reason" : undefined}
                      onClick={() => { if (!busy) rollbackDryRun(); }}>Roll back: dry run</button>
            )}
            {deleteOffered && (
              <button className="btn danger sm" aria-disabled={busy || undefined}
                      onClick={() => { if (!busy) setConfirming(true); }}>Delete these objects…</button>
            )}
            {recordOffered && (
              <button className="btn secondary sm" aria-disabled={busy || undefined}
                      onClick={() => { if (!busy) setConfirming(true); }}>Record the rollback…</button>
            )}
          </>}>
      {outcome}
      {unlockProblem && <Notice tone="warning" title="This rollback dry run can't be used for a rollback">{unlockProblem.charAt(0).toUpperCase() + unlockProblem.slice(1)}.</Notice>}
      {next && <p className="small"><b>Next:</b> {next}</p>}
      {rolledBack && <p className="small">Rolled back by run <button className="btn link" onClick={() => onOpen(rolledBack.apply_id)}>{String(rolledBack.apply_id).slice(0, 8)}</button> ({String(rolledBack.status).toLowerCase()}).</p>}
      {rollbackOffered && rollbackReason && <Reason id="rollback-reason">Roll back is unavailable. {rollbackReason}</Reason>}
      {jobId && <JobLine state={job} label={rollbackDry ? "Rollback" : "Rollback dry run"} />}
      {err && <ErrorBox error={err} title="Couldn't start the rollback" />}
      <Table label="Apply results" rows={data.items} pageSize={50} empty={<Empty title="No objects">This run didn't create, change or check anything.</Empty>} columns={[
        { key: "type", label: "Object", render: (i) => i.type?.replace(/_/g, " ") },
        { key: "name", label: "Name", render: (i) => <code className="wrap">{i.name}</code> },
        { key: "action", label: "Result", render: (i) => <Badge value={i.action} /> },
        { key: "reason", label: "Details", sortable: false, render: (i) => <span className="small">{itemDetails(i)}</span> },
      ]} />
      {confirming && (
        <Confirm word="ROLLBACK" title={toDelete.length ? "Roll back" : "Record the rollback"}
                 action={toDelete.length ? `Delete ${plural(toDelete.length, "object")}` : "Record the rollback"} busy={busy}
                 onCancel={() => setConfirming(false)} onConfirm={rollback}
                 body={<>
                   {data.meta?.workspace_id && <p>In workspace <b>{data.meta.workspace_id}</b> (where the execute run created them).</p>}
                   {toDelete.length ? <>
                     <p>Delete the {plural(toDelete.length, "object")} this dry run listed:</p>
                     <ul className="small">{toDelete.slice(0, 12).map((i: any) => <li key={i.type + i.name}><code>{i.name}</code> ({String(i.type).replace(/_/g, " ")})</li>)}</ul>
                   </> : <p>This dry run found nothing to delete, and the rollback deletes only what its dry run listed. Running it records the result, so the execute run counts as rolled back where everything left is gone, used by another run, or older than the run.</p>}
                   <p className="small">Only these are deleted: anything else, even something that became deletable since the dry run, is kept and the result says so. Objects another run still uses are kept. Inference tables stay. Grants are never revoked: a deleted service takes its grants with it, and a kept service keeps them (the results list them).</p>
                   <Notice tone="warning">If callers have already moved to these endpoints, rolling back breaks their traffic. Move them back first.</Notice>
                 </>} />
      )}
    </Card>
  );
}
