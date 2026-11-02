import { useCallback, useEffect, useState } from "react";
import { useApi } from "./api";
import Apply from "./Apply";
import Cutover from "./Cutover";
import Overview from "./Overview";
import Scans from "./Scans";
import { Badge, Card, ErrorBoundary, Goto, LiveRegion, Notice, NavContext, PageHeader, Tabs, tabPanel } from "./ui";

export const PRODUCT = "Unity Gateway Migration Toolkit";

/** "March 30, 2027" from the installer's ISO date (the default when the config isn't loaded yet). */
export function deadlineText(iso?: string) {
  const d = iso ? new Date(`${iso}T00:00:00Z`) : null;
  return d && !Number.isNaN(d.getTime())
    ? d.toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric", timeZone: "UTC" })
    : "March 30, 2027";
}

const TABS = [["overview", "Overview"], ["scans", "Scans"], ["apply", "Apply"], ["cutover", "Verify & cut over"], ["about", "About"]] as const;

type Route = { tab: string; anchor: string | null; seq: number };

export default function App() {
  const [route, setRoute] = useState<Route>({ tab: "overview", anchor: null, seq: 0 });
  const [scanForApply, setScanForApply] = useState<string | null>(null);
  const me = useApi<any>("/api/whoami");
  const config = useApi<any>("/api/config");
  const operator = !!me.data?.operator;
  const tab = route.tab;
  // Switch section, and optionally land on an element inside it (see HowToEnforce).
  const goto: Goto = useCallback((t, anchor) => setRoute((r) => ({ tab: t, anchor: anchor ?? null, seq: r.seq + 1 })), []);
  useEffect(() => { document.title = `${TABS.find(([k]) => k === tab)?.[1]} · ${PRODUCT}`; }, [tab]);
  // After the section shows, move focus to the anchor inside it.
  useEffect(() => {
    if (!route.anchor) return;
    const el = document.getElementById(route.anchor);
    if (!el) return;
    el.setAttribute("tabindex", "-1");
    el.scrollIntoView({ block: "start" });
    el.focus({ preventScroll: true });
  }, [route]);
  return (
    <NavContext.Provider value={goto}>
      <div className="app">
        <a className="skip-link" href="#main">Skip to content</a>
        <LiveRegion />
        <header className="top">
          <h1>{PRODUCT}</h1>
          <Tabs className="tabs" label="Sections" tabs={TABS} value={tab} onChange={(k) => goto(k)} panelId="sections" />
          <div className="me">
            {me.data && (me.data.email
              ? <><span>{me.data.email}</span><Badge value={me.data.operator ? "Operator" : "View only"} tone={me.data.operator ? "info" : "neutral"} /></>
              : <Badge value="Not signed in" tone="warn" />)}
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
          <div {...tabPanel("sections", tab)} className="section-panel">
            <div hidden={tab !== "overview"}><ErrorBoundary><Overview operator={operator} /></ErrorBoundary></div>
            <div hidden={tab !== "scans"}><ErrorBoundary><Scans operator={operator} onApply={(id) => { setScanForApply(id); goto("apply"); }} /></ErrorBoundary></div>
            <div hidden={tab !== "apply"}><ErrorBoundary><Apply operator={operator} scanRunId={scanForApply} setScanRunId={setScanForApply} /></ErrorBoundary></div>
            <div hidden={tab !== "cutover"}><ErrorBoundary><Cutover operator={operator} maxScanAgeDays={config.data?.max_scan_age_days ?? 14} /></ErrorBoundary></div>
            <div hidden={tab !== "about"}><About user={me.data} config={config.data} /></div>
          </div>
        </main>
        <footer className="muted small">Prototype from Databricks Shared Technical Services, provided as is. Review results before acting on them.</footer>
      </div>
    </NavContext.Provider>
  );
}

function About({ user, config }: { user: any; config: any }) {
  return (
    <div className="stack">
      <PageHeader title="About" description="Moves this workspace's legacy model serving endpoints to Unity Gateway, from inventory to a verified cut-over. Only operators change a legacy endpoint, one step at a time, after a dry run." />
      <Card title="What the app does, in order">
        <ol>
          <li><b>Inventory (Overview, Scans).</b> Every workspace, its wave and the share already on Unity Gateway. A scan reads one workspace's endpoints, callers and code, and says whether enforcing is safe.</li>
          <li><b>Migrate (Apply).</b> Creates the Unity Gateway services for external model and Provisioned Throughput endpoints: dry run, then execute the same selection. Legacy endpoints are not changed here.</li>
          <li><b>Verify & cut over.</b> Checks that legacy traffic has stopped, turns on usage tracking, pauses legacy endpoints one at a time (and resumes them), and tests Unity Gateway services with a billable test call.</li>
          <li><b>Analyze Unity Gateway traffic (Verify & cut over).</b> Requests, latency, tokens and errors per service, workspace, requester and API type, with a CSV export.</li>
          <li><b>Enforce (in the workspace).</b> Turn on Enforce Unity Gateway in Settings &gt; Advanced. The app never changes that setting.</li>
        </ol>
      </Card>
      <Card id="how-to-enforce" title="How to enforce">
        <p>Enforcing is the Enforce Unity Gateway setting in the workspace admin settings (Settings &gt; Advanced &gt; Enforce Unity Gateway). It makes databricks-* pay-per-token calls fail with PERMISSION_DENIED, so turn it on only after the scan says READY (or READY_WITH_WARNINGS with the warnings accepted) and callers have moved.</p>
        <p>READY also needs zero legacy requests in the scan window (30 days by default), so callers that moved recently still show. Scan with a shorter window (7 days) to watch progress.</p>
      </Card>
      <Card title="Deadline">
        <p>Every legacy endpoint (v1 and v2) stops serving on <b>{deadlineText(config?.deadline)}</b>. Custom model and feature serving endpoints aren't affected. Government cloud workspaces can have different dates: ask your account team. Settings on legacy endpoints don't carry over. The date is confirmed as of November 1, 2026.</p>
      </Card>
      <Card title="Access and safety">
        <ul>
          <li>Pages read results as you ({user?.user_authorization ? "user authorization is on" : "user authorization is off, so results can't be read until it's turned on"}). Unity Catalog permissions on the results schema{config?.results_schema ? <> (<code>{config.results_schema}</code>)</> : null} apply.</li>
          <li>Snapshots, scans and apply runs are jobs that run as the identity that installed the app. Only operators can start them.</li>
          <li>Execute and rollback need a typed confirmation. Execute only follows a successful dry run of the same selection. Grants are off unless you choose them.</li>
          <li>Scans store matched code lines with credential-looking values hidden: keep the results schema to the migration team.</li>
          <li>Provider API keys come from Unity Catalog secrets in the schemas the installer allowed. Copying key values is off unless the installer enabled it.</li>
          <li>Pausing, usage tracking and resuming need an operator, a dry run and a typed word. A test call is billable: it sends one request per service.</li>
        </ul>
      </Card>
      <Card title="Glossary">
        <dl className="glossary">
          <div><dt>Legacy (v1 and v2)</dt><dd>Calls to the older serving endpoints (v1) and AI Gateway v2 calls, as recorded in the system tables.</dd></div>
          <div><dt>Unity Gateway</dt><dd>The target: AI Gateway calls with service type MODEL_SERVICE.</dd></div>
          <div><dt>Provider service</dt><dd>The connection to an external model provider (for example OpenAI or Anthropic), with its API key from a secret.</dd></div>
          <div><dt>Model service</dt><dd>The Unity Gateway endpoint your callers use. It routes to a provider service or a Provisioned Throughput endpoint.</dd></div>
          <div><dt>Service policy</dt><dd>Settings on a model service such as rate limits and guardrails. Guardrails aren't copied: re-create them as service policies.</dd></div>
          <div><dt>Inference table</dt><dd>The Unity Catalog table where an endpoint logs its requests. Rollback keeps inference tables.</dd></div>
          <div><dt>Provisioned Throughput (PT)</dt><dd>Dedicated capacity for a foundation model endpoint.</dd></div>
          <div><dt>Databricks pay-per-token</dt><dd>Models hosted by Databricks. Their system AI services already exist, so they need nothing.</dd></div>
          <div><dt>Scan</dt><dd>A readiness check of one workspace: endpoints, callers and code. READY and READY_WITH_WARNINGS pass.</dd></div>
          <div><dt>Wave</dt><dd>Where a workspace falls on the Overview, based on its traffic.</dd></div>
          <div><dt>Customer-owned</dt><dd>Requests from your code and jobs (any caller that isn't Databricks-managed).</dd></div>
          <div><dt>Databricks-managed</dt><dd>Requests from Databricks features, for example Genie or Agent Bricks. You can't change these; confirm with your account team how they move.</dd></div>
        </dl>
      </Card>
    </div>
  );
}
