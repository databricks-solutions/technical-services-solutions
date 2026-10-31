import { useState } from "react";
import { api, fmt, jobRunning, pct, useApi, useJob } from "./api";
import { Badge, Bars, Card, Empty, ErrorBox, ErrorState, ExportMenu, JobLine, Kpi, PageHeader, SkeletonCard, SkeletonKpis, Table, TrendChart } from "./ui";

const WAVE_TONE = (w: string) => (w.startsWith("0") ? "good" : w.startsWith("v2") || w.startsWith("2") ? "bad" : "warn");

export default function Overview({ operator }: { operator: boolean }) {
  const { data, error, loading, reload } = useApi<any>("/api/overview");
  const [jobId, setJobId] = useState<string | null>(null);
  const [startErr, setStartErr] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const job = useJob(jobId, () => reload());

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

  const running = jobRunning(jobId, job);
  const refreshButton = (
    <button className="btn" onClick={refresh} disabled={!operator || starting || running}
            title={operator ? undefined : "Only operators can start jobs"}>
      {starting || running ? "Refreshing…" : "Refresh snapshot"}
    </button>
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

  return (
    <div className="stack">
      <PageHeader title="Account overview"
                  description={latest ? <>Latest snapshot {data.snapshot_time} UTC · from this account's system tables · legacy = v1 + v2 requests</> : undefined}
                  actions={<>{exports}{refreshButton}</>} />
      {jobId && <JobLine state={job} label="Snapshot" done="The overview now shows the new snapshot." />}
      {startErr && <ErrorBox error={startErr} />}

      {loading && !data ? (
        <>
          <SkeletonKpis />
          <div className="grid2"><SkeletonCard title="Traffic" block /><SkeletonCard title="Workspaces by wave" block /></div>
          <SkeletonCard title="Workspaces" />
        </>
      ) : error ? (
        <ErrorState error={error} onRetry={reload} title="Couldn't load the account snapshot" />
      ) : !latest ? (
        <Empty title="No snapshot yet"
               action={operator ? refreshButton : <span className="small">Ask an operator to refresh the snapshot.</span>}>
          A snapshot reads this account's system tables (a few minutes, including job start-up).
        </Empty>
      ) : (
        <>
          <div className="kpis">
            <Kpi label="Legacy requests" value={fmt(latest.legacy_requests)} sub="v1 + v2, traffic window" tone={Number(latest.legacy_requests) ? "bad" : "good"} />
            <Kpi label="Share on Unity Gateway" value={pct(Number(latest.v3_requests) / Math.max(1, Number(latest.v3_requests) + Number(latest.legacy_requests)))} sub={`${fmt(latest.v3_requests)} requests`} />
            <Kpi label="Active legacy endpoints" value={fmt(latest.active_legacy_endpoints)} sub="v1, with traffic" tone={Number(latest.active_legacy_endpoints) ? "warn" : "good"} />
            <Kpi label="Ready to enforce" value={`${fmt(latest.enforce_candidates)} of ${fmt(latest.workspaces)}`} sub="workspaces in wave 0" tone={Number(latest.enforce_candidates) ? "good" : undefined} />
          </div>
          <div className="grid2">
            <Card title="Legacy vs Unity Gateway traffic" note="Requests per snapshot">
              <TrendChart label="Legacy vs Unity Gateway requests" points={data.trend}
                          series={[{ key: "legacy_requests", label: "Legacy (v1 + v2)", cls: "legacy" }, { key: "v3_requests", label: "Unity Gateway", cls: "ug" }]} />
            </Card>
            <Card title="Workspaces ready to enforce" note="Wave 0 workspaces per snapshot">
              <TrendChart label="Workspaces ready to enforce" points={data.trend} series={[{ key: "enforce_candidates", label: "Ready to enforce", cls: "single" }]} />
            </Card>
          </div>
          <Card title="Workspaces by migration wave" note="v2 first: v2 endpoints stop serving November 30, 2026. Wave 0: no legacy traffic and no external model or Provisioned Throughput endpoints.">
            <Bars label="Workspaces by migration wave" rows={data.waves} labelKey="wave" valueKey="workspaces" />
          </Card>
          <Card title="Workspaces" note="Busiest first. Scan a workspace for its details.">
            <Table search label="Workspaces" rows={data.workspaces} columns={[
              { key: "workspace_name", label: "Workspace", render: (r) => <><b>{r.workspace_name || "-"}</b><div className="muted small">{r.workspace_id}</div></> },
              { key: "wave", label: "Wave", render: (r) => <Badge value={r.wave} tone={WAVE_TONE(String(r.wave))} /> },
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
          <Card title="Busiest legacy v1 endpoints" note={`Top ${data.endpoints_limit || 100} by requests. Export for the full list.`}>
            <Table search label="Busiest legacy endpoints" rows={data.endpoints} empty="No legacy v1 traffic in the window" columns={[
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
