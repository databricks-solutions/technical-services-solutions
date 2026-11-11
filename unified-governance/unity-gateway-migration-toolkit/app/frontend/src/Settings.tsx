import { useState } from "react";
import { api, useApi } from "./api";
import { Badge, Card, ErrorBox, ErrorState, Notice, PageHeader, Reason, SkeletonCard, Table, announce } from "./ui";

/** Operators: the people who can start snapshots, scans, apply and cut-over steps. Workspace admins change the list. */
export default function Settings() {
  const ops = useApi<any>("/api/settings/operators");
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const canEdit = !!ops.data?.can_edit;

  const change = async (target: string, add: boolean) => {
    setBusy(true);
    setErr(null);
    try {
      await api("/api/settings/operators", { method: "POST", body: JSON.stringify({ email: target, add }) });
      if (add) setEmail("");
      announce(add ? `Added ${target} as an operator` : `Removed ${target} from the operators`);
      ops.reload();
    } catch (e: any) {
      setErr(String(e.message || e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="stack">
      <PageHeader title="Settings" description="Operators start snapshots, scans, apply runs and cut-over steps. Everyone else with access to the app can view results. Only workspace admins change the operators." />
      {ops.error ? <ErrorState error={ops.error} onRetry={ops.reload} /> : !ops.data ? <SkeletonCard title="Operators" /> : (
        <Card title="Operators">
          {ops.data.error && <Notice tone="warning" title="The operators list couldn't be read">{ops.data.error}</Notice>}
          <Table label="Operators" rows={ops.data.operators || []}
                 empty="No operators yet. A workspace admin can add one below." columns={[
            { key: "email", label: "Email" },
            { key: "source", label: "Set in", render: (r) => r.source === "deployment"
              ? <Badge value="App deployment" tone="neutral" /> : <Badge value="Settings" tone="info" /> },
            { key: "added_by", label: "Added by", hideOnPhone: true, render: (r) => r.added_by || "-" },
            { key: "added_at", label: "Added", hideOnPhone: true, render: (r) => r.added_at ? String(r.added_at).slice(0, 16) : "-" },
            { key: "remove", label: "", render: (r) => canEdit && r.source === "app"
              ? <button className="btn link sm" disabled={busy} aria-label={`Remove ${r.email}`} onClick={() => change(r.email, false)}>Remove</button>
              : null },
          ]} />
          {canEdit ? (
            <form className="row" onSubmit={(e) => { e.preventDefault(); if (email.trim()) change(email.trim(), true); }}>
              <div className="field-group">
                <label className="field" htmlFor="operator-email">Add an operator (email)</label>
                <input id="operator-email" type="email" value={email} disabled={busy} placeholder="someone@example.com"
                       onChange={(e) => setEmail(e.target.value)} />
              </div>
              <button className="btn" type="submit" disabled={busy || !email.trim()}>Add</button>
            </form>
          ) : <Reason id="operators-edit">Only workspace admins can add or remove operators.</Reason>}
          {err && <ErrorBox error={err} title="The operators didn't change" />}
          <p className="muted small">Operators set in the app deployment (the bundle's operators variable) are changed there, not here.</p>
        </Card>
      )}
    </div>
  );
}
