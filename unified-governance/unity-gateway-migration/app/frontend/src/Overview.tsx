import { useState } from "react";
import { api, fmt, jobRunning, pct, useApi, useJob } from "./api";
import { Badge, Bars, Card, Empty, ErrorBox, JobLine, Kpi, Loading, Table, TrendChart } from "./ui";

export default function Overview({ operator }: { operator: boolean }) {
  const { data, error, loading, reload } = useApi<any>("/api/overview");
  const [jobId, setJobId] = useState<string | null>(null);
  const [startErr, setStartErr] = useState<string | null>(null);
  const job = useJob(jobId, () => reload());

  const [starting, setStarting] = useState(false);
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

  const actions = (
    <button onClick={refresh} disabled={!operator || starting || jobRunning(jobId, job)} title={operator ? "" : "Only the app's operators can start jobs"}>Refresh account snapshot</button>
  );
  if (loading && !data) return <Loading text="Loading account snapshot" />;
  if (error) return (
    <div className="stack">
      <h2>Account overview</h2>
      <ErrorBox error={error} />
      <div className="row"><button className="ghost" onClick={reload}>Retry</button>{actions}</div>
      {jobId && <JobLine state={job} label="Snapshot" />}{startErr && <ErrorBox error={startErr} />}
    </div>
  );
  const latest = data?.trend?.[data.trend.length - 1];
  return (
    <div className="stack">
      <div className="row between">
        <div>
          <h2>Account overview</h2>
          <p className="muted small">
            {data?.snapshot_time ? <>Latest snapshot {data.snapshot_time} UTC, from this account's system tables. Legacy = v1 + v2 requests (distinct request IDs).</> : "No snapshot yet."}
          </p>
        </div>
        <div className="stack-tight end">{actions}{jobId && <JobLine state={job} label="Snapshot" />}{startErr && <ErrorBox error={startErr} />}</div>
      </div>
      {!latest ? (
        <Empty>Run "Refresh account snapshot" to take the first snapshot (a few minutes, including job start-up).</Empty>
      ) : (
        <>
          <div className="kpis">
            <Kpi label="Legacy requests (v1 + v2)" value={fmt(latest.legacy_requests)} sub="in the traffic window" tone={Number(latest.legacy_requests) ? "bad" : "good"} />
            <Kpi label="Share on Unity Gateway" value={pct(Number(latest.v3_requests) / Math.max(1, Number(latest.v3_requests) + Number(latest.legacy_requests)))} sub={`${fmt(latest.v3_requests)} Unity Gateway requests`} />
            <Kpi label="Active legacy endpoints" value={fmt(latest.active_legacy_endpoints)} sub="v1 endpoints with traffic" tone={Number(latest.active_legacy_endpoints) ? "warn" : "good"} />
            <Kpi label="Enforce candidates" value={`${fmt(latest.enforce_candidates)} / ${fmt(latest.workspaces)}`} sub="workspaces in wave 0" tone={Number(latest.enforce_candidates) ? "good" : undefined} />
          </div>
          <div className="grid2">
            <Card title="Legacy vs Unity Gateway traffic" note="One point per snapshot.">
              <TrendChart points={data.trend} series={[{ key: "legacy_requests", label: "Legacy (v1 + v2)", cls: "s-bad" }, { key: "v3_requests", label: "Unity Gateway", cls: "s-good" }]} />
            </Card>
            <Card title="Workspaces by migration wave" note="v2 first: v2 endpoints stop serving on November 30, 2026. Wave 0: no legacy traffic and no external model or Provisioned Throughput (PT) endpoints.">
              <Bars rows={data.waves} labelKey="wave" valueKey="workspaces" />
            </Card>
          </div>
          <Card title="Workspaces" note="Busiest first. Run a workspace scan from the Scans tab for the details of one workspace.">
            <Table search rows={data.workspaces} columns={[
              { key: "workspace_name", label: "Workspace", render: (r) => <><b>{r.workspace_name || "-"}</b><div className="muted small">{r.workspace_id}</div></> },
              { key: "wave", label: "Wave", render: (r) => <Badge value={r.wave} tone={String(r.wave).startsWith("0") ? "good" : String(r.wave).startsWith("v2") || String(r.wave).startsWith("2") ? "bad" : "warn"} /> },
              { key: "legacy_endpoints", label: "Legacy endpoints", num: true, render: (r) => fmt(r.legacy_endpoints) },
              { key: "custom_legacy_endpoints", label: "External model / PT", num: true, render: (r) => fmt(r.custom_legacy_endpoints) },
              { key: "active_legacy_endpoints", label: "Active", num: true, render: (r) => fmt(r.active_legacy_endpoints) },
              { key: "v1_requests", label: "v1 requests", num: true, render: (r) => fmt(r.v1_requests) },
              { key: "v2_requests", label: "v2 requests", num: true, render: (r) => fmt(r.v2_requests) },
              { key: "legacy_throttled", label: "Throttled", num: true, render: (r) => fmt(r.legacy_throttled) },
              { key: "v3_requests", label: "Unity Gateway", num: true, render: (r) => fmt(r.v3_requests) },
              { key: "v3_share", label: "Share on UG", num: true, render: (r) => pct(r.v3_share) },
            ]} />
          </Card>
          <Card title="Busiest legacy v1 endpoints" note={`Top ${data.endpoints_limit || 100} by requests in the latest snapshot.`}>
            <Table search rows={data.endpoints} empty="No legacy v1 traffic in the window." columns={[
              { key: "workspace_name", label: "Workspace" },
              { key: "endpoint_name", label: "Endpoint", render: (r) => <code>{r.endpoint_name}</code> },
              { key: "kind", label: "Kind" },
              { key: "requests", label: "Requests", num: true, render: (r) => fmt(r.requests) },
              { key: "requesters", label: "Callers", num: true, render: (r) => fmt(r.requesters) },
              { key: "throttled", label: "Throttled", num: true, render: (r) => fmt(r.throttled) },
              { key: "last_request", label: "Last request", render: (r) => String(r.last_request || "").slice(0, 16) },
            ]} />
          </Card>
        </>
      )}
    </div>
  );
}
