import { useState } from "react";
import { useApi } from "./api";
import Apply from "./Apply";
import Overview from "./Overview";
import Scans from "./Scans";
import { Card, ErrorBoundary } from "./ui";

const TABS = [["overview", "Overview"], ["scans", "Scans"], ["apply", "Apply"], ["about", "About"]] as const;

export default function App() {
  const [tab, setTab] = useState<string>("overview");
  const [scanForApply, setScanForApply] = useState<string | null>(null);
  const me = useApi<any>("/api/whoami");
  const operator = !!me.data?.operator;
  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <span className="logo">UG</span>
          <div>
            <div className="title">Unity Gateway Migration</div>
            <div className="subtitle">Move legacy model serving endpoints to Unity Gateway</div>
          </div>
        </div>
        <nav className="tabs" role="tablist">
          {TABS.map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>{l}</button>)}
        </nav>
        <div className="me small">
          {me.error && <div className="alert bad small" role="alert">Couldn't confirm your access: {me.error} <button className="ghost small" onClick={me.reload}>Retry</button></div>}
          {me.data && <><span className="badge neutral">{me.data.email}</span><div className="muted">{me.data.user_authorization ? "Results read as you" : "Results read as the app"}{me.data.operator ? ", operator" : ", view only"}</div></>}
        </div>
      </header>
      <main>
        {/* Tabs stay mounted so a running job keeps its status line when you switch tabs. */}
        <div hidden={tab !== "overview"}><ErrorBoundary><Overview operator={operator} /></ErrorBoundary></div>
        <div hidden={tab !== "scans"}><ErrorBoundary><Scans operator={operator} onApply={(id) => { setScanForApply(id); setTab("apply"); }} /></ErrorBoundary></div>
        <div hidden={tab !== "apply"}><ErrorBoundary><Apply operator={operator} scanRunId={scanForApply} setScanRunId={setScanForApply} /></ErrorBoundary></div>
        <div hidden={tab !== "about"}><About /></div>
      </main>
      <footer className="muted small">Prototype from Databricks Shared Technical Services, provided as is. Review results before acting on them.</footer>
    </div>
  );
}

function About() {
  return (
    <div className="stack">
      <h2>About</h2>
      <Card title="Why migrate">
        <p>Legacy v2 workspace endpoints stop serving first (on <b>November 30, 2026</b>) and v1 model serving endpoints stop serving on <b>March 30, 2027</b> (dates from Databricks migration communications as of October 30, 2026; confirm with your account team). Nothing moves automatically, and settings on legacy endpoints (rate limits, guardrails, inference tables, permissions) don't carry over.</p>
      </Card>
      <Card title="How to use this app">
        <ol>
          <li><b>Overview:</b> take an account snapshot to see every workspace with legacy traffic, its wave, and the share already on Unity Gateway.</li>
          <li><b>Scans:</b> scan a workspace (read-only). Readiness tells you whether Enforce Unity Gateway is safe; Callers and Code fixes show who has to change what.</li>
          <li><b>Apply:</b> for external model and PT endpoints, dry run, then execute to create the Unity Gateway services and grants. The target schema (from the scan form) must exist and the jobs' identity needs <code>CREATE SERVICE</code> on it. Roll back from the history if needed.</li>
          <li>Move callers using the code fixes, scan again, and enable <i>Enforce Unity Gateway</i> (Settings, Advanced) when the workspace is READY.</li>
        </ol>
      </Card>
      <Card title="Identity and permissions">
        <ul>
          <li>Pages read results from Delta tables as the signed-in user, so Unity Catalog permissions on the results schema apply.</li>
          <li>Snapshots, scans and apply runs execute as Lakeflow jobs under the identity that installed the app (use a service principal for shared installs). The app's service principal can only start these jobs, and only the app's operators can ask it to. Everyone else can view results. Every run records who asked for it.</li>
          <li>Execute and rollback need a typed confirmation. Apply never changes or deletes legacy endpoints. The only commands that touch a legacy endpoint are the optional close commands on the Readiness tab, which you copy and run yourself.</li>
          <li>Scans store matched code lines in the results schema (credential-looking values are hidden), so keep that schema limited to the migration team.</li>
        </ul>
      </Card>
    </div>
  );
}
