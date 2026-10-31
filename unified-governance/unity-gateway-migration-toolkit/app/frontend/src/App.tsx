import { useEffect, useState } from "react";
import { useApi } from "./api";
import Apply from "./Apply";
import Overview from "./Overview";
import Scans from "./Scans";
import { Badge, Card, ErrorBoundary, Notice, PageHeader, Tabs } from "./ui";

export const PRODUCT = "Unity Gateway Migration Toolkit";

const TABS = [["overview", "Overview"], ["scans", "Scans"], ["apply", "Apply"], ["about", "About"]] as const;

export default function App() {
  const [tab, setTab] = useState<string>("overview");
  const [scanForApply, setScanForApply] = useState<string | null>(null);
  const me = useApi<any>("/api/whoami");
  const operator = !!me.data?.operator;
  useEffect(() => { document.title = `${TABS.find(([k]) => k === tab)?.[1]} · ${PRODUCT}`; }, [tab]);
  return (
    <div className="app">
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="top">
        <h1>{PRODUCT}</h1>
        <Tabs className="tabs" label="Sections" tabs={TABS} value={tab} onChange={setTab} />
        <div className="me">
          {me.data && <><span>{me.data.email}</span><Badge value={me.data.operator ? "Operator" : "View only"} tone={me.data.operator ? "info" : "neutral"} /></>}
        </div>
      </header>
      <main id="main" tabIndex={-1}>
        {me.error && (
          <div style={{ marginBottom: 16 }}>
            <Notice tone="warning" title="Couldn't confirm your access" action={<button className="btn secondary sm" onClick={me.reload}>Try again</button>}>
              Results may still load; starting jobs is disabled until your access is confirmed.
            </Notice>
          </div>
        )}
        {/* Sections stay mounted so a running job keeps its status when you switch tabs. */}
        <div hidden={tab !== "overview"}><ErrorBoundary><Overview operator={operator} /></ErrorBoundary></div>
        <div hidden={tab !== "scans"}><ErrorBoundary><Scans operator={operator} onApply={(id) => { setScanForApply(id); setTab("apply"); }} /></ErrorBoundary></div>
        <div hidden={tab !== "apply"}><ErrorBoundary><Apply operator={operator} scanRunId={scanForApply} setScanRunId={setScanForApply} /></ErrorBoundary></div>
        <div hidden={tab !== "about"}><About user={me.data} /></div>
      </main>
      <footer className="muted small">Prototype from Databricks Shared Technical Services, provided as is. Review results before acting on them.</footer>
    </div>
  );
}

function About({ user }: { user: any }) {
  return (
    <div className="stack">
      <PageHeader title="About" />
      <Card title="Deadlines">
        <p>Legacy v2 workspace endpoints stop serving on <b>November 30, 2026</b>; v1 model serving endpoints on <b>March 30, 2027</b>. Settings on legacy endpoints don't carry over. Dates as of October 30, 2026: confirm with your account team.</p>
      </Card>
      <Card title="How to use it">
        <ol>
          <li><b>Overview:</b> refresh the account snapshot to see every workspace, its migration wave and the share already on Unity Gateway.</li>
          <li><b>Scans:</b> scan a workspace. Readiness says whether Enforce Unity Gateway is safe; Callers and Code fixes show who has to change what.</li>
          <li><b>Apply:</b> for external model and Provisioned Throughput endpoints, dry run, then execute. The target schema must exist and the jobs' identity needs <code>CREATE SERVICE</code> on it.</li>
          <li>Move callers, scan again, and turn on <i>Enforce Unity Gateway</i> (Settings, Advanced) when the workspace is READY.</li>
        </ol>
      </Card>
      <Card title="Access and safety">
        <ul>
          <li>Pages read results as you ({user?.user_authorization ? "user authorization is on" : "user authorization is off: results are read as the app"}), so Unity Catalog permissions on the results schema apply.</li>
          <li>Snapshots, scans and apply runs are jobs that run as the identity that installed the app. Only operators can start them.</li>
          <li>Execute and rollback need a typed confirmation. Apply never changes legacy endpoints.</li>
          <li>Scans store matched code lines (credential-looking values hidden): keep the results schema limited to the migration team.</li>
        </ul>
      </Card>
    </div>
  );
}
