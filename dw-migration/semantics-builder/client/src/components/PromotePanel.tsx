import { useState } from 'react';
import {
  Alert,
  Button,
  Checkbox,
  FormUI,
  Input,
  Modal,
  Table,
  TableCell,
  TableHeader,
  TableRow,
  Tag,
  Typography,
} from '@databricks/design-system';
import type { PromotionView } from '../../../shared/promote';
import { api, useResource } from '../api';
import type { ApprovalState } from '../../../shared/review';
import { ApprovalPanel, approved } from './ApprovalPanel';
import { DataState } from './DataState';
import { ImpactPanel } from './ImpactPanel';
import { OpenInCatalog } from './OpenInCatalog';
import { SqlBlock } from './SqlBlock';

/** Set the Unity Catalog view of the sub-project, and promote the latest validated version to it, as the user. */
export function PromotePanel({ projectId, onPromoted }: { projectId: string; onPromoted?: () => void }) {
  const data = useResource<PromotionView>(`/api/projects/${projectId}/promotion`);
  const approval = useResource<ApprovalState>(`/api/projects/${projectId}/approval`);
  const [target, setTarget] = useState<string>();
  const [reviewing, setReviewing] = useState(false);
  const [overwrite, setOverwrite] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const v = data.data;
  const plan = v?.plan;
  const last = v?.promotions.find((p) => p.status === 'succeeded');

  const post = (path: string, body: unknown, after?: () => void) => {
    setBusy(true);
    setError(undefined);
    api<PromotionView>(path, body).then(
      (next) => {
        setBusy(false);
        data.setData(next);
        after?.();
      },
      (err: unknown) => {
        setBusy(false);
        setError((err as Error).message);
      }
    );
  };

  return (
    <DataState status={data.status} message={data.error} onRetry={data.reload}>
      {v && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 960 }}>
          <Typography.Text color="secondary">
            Promote puts the latest validated version in Unity Catalog, where dashboards, Genie and SQL users find it.
            It creates or replaces the view, as you. To roll back, restore an older version in Metric Designer, History,
            validate it, then promote it.
          </Typography.Text>
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
            <div style={{ minWidth: 420 }}>
              <FormUI.Label htmlFor="pp-target">Unity Catalog view</FormUI.Label>
              <FormUI.Hint>catalog.schema.view. Not the sandbox schema.</FormUI.Hint>
              <Input
                componentId="gsb.promote.target"
                id="pp-target"
                placeholder="main.sales.order_metrics"
                value={target ?? v.target ?? ''}
                onChange={(e) => setTarget(e.target.value)}
              />
            </div>
            <Button
              componentId="gsb.promote.set_target"
              disabled={busy || !target || target === v.target}
              onClick={() =>
                post(`/api/projects/${projectId}/promotion/target`, { fullName: target }, () => setTarget(undefined))
              }
            >
              Save the target
            </Button>
            {v.target && <OpenInCatalog fullName={v.target} />}
          </div>

          {last && (
            <Typography.Text>
              Version <b>{last.version}</b> is in Unity Catalog, promoted by {last.createdBy} on{' '}
              {new Date(last.createdAt).toLocaleString()}.
              {plan && plan.version !== last.version ? ` Version ${plan.version} is newer.` : ''}
            </Typography.Text>
          )}
          {v.problem && <Alert componentId="gsb.promote.problem" type="info" closable={false} message={v.problem} />}
          {approval.data && (
            <ApprovalPanel
              projectId={projectId}
              state={approval.data}
              version={plan?.version}
              onChange={approval.setData}
            />
          )}
          {plan && (
            <div>
              <Button
                componentId="gsb.promote.review"
                type="primary"
                disabled={busy || !approval.data || !approved(approval.data, plan.version)}
                onClick={() => {
                  setOverwrite(false);
                  setReviewing(true);
                }}
              >
                Promote version {plan.version}
              </Button>
            </div>
          )}
          {error && <Alert componentId="gsb.promote.error" type="error" closable={false} message={error} />}

          {v.promotions.length > 0 && (
            <Table aria-label="Promotions">
              <TableRow isHeader>
                <TableHeader componentId="gsb.promote.h_version">Version</TableHeader>
                <TableHeader componentId="gsb.promote.h_target">View</TableHeader>
                <TableHeader componentId="gsb.promote.h_status">Status</TableHeader>
                <TableHeader componentId="gsb.promote.h_by">By</TableHeader>
                <TableHeader componentId="gsb.promote.h_when">When</TableHeader>
              </TableRow>
              {v.promotions.map((p) => (
                <TableRow key={p.id}>
                  <TableCell>{p.version}</TableCell>
                  <TableCell>{p.target}</TableCell>
                  <TableCell>
                    <Tag
                      componentId="gsb.promote.status"
                      color={p.status === 'succeeded' ? 'teal' : p.status === 'failed' ? 'coral' : 'lemon'}
                      title={p.error ?? undefined}
                    >
                      {p.status === 'succeeded' ? 'Promoted' : p.status === 'failed' ? 'Failed' : 'Running'}
                    </Tag>
                  </TableCell>
                  <TableCell>{p.createdBy}</TableCell>
                  <TableCell>{new Date(p.createdAt).toLocaleString()}</TableCell>
                </TableRow>
              ))}
            </Table>
          )}

          {plan && (
            <Modal
              componentId="gsb.promote.modal"
              title={`Promote version ${plan.version} to ${v.target ?? ''}`}
              visible={reviewing}
              okText="Run SQL"
              cancelText="Cancel"
              okButtonProps={{ loading: busy, disabled: plan.changedOutside && !overwrite }}
              onCancel={() => setReviewing(false)}
              onOk={() =>
                post(
                  `/api/projects/${projectId}/promotion`,
                  { version: plan.version, statement: plan.statement, overwrite },
                  () => {
                    setReviewing(false);
                    onPromoted?.();
                  }
                )
              }
            >
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <Alert
                  componentId="gsb.promote.warning"
                  type="warning"
                  closable={false}
                  message={
                    plan.exists
                      ? 'This replaces the view in Unity Catalog, as you. Queries, dashboards and Genie spaces on it see the new definition at once.'
                      : 'This creates the view in Unity Catalog, as you.'
                  }
                />
                {plan.changedOutside && (
                  <>
                    <Alert
                      componentId="gsb.promote.changed"
                      type="error"
                      closable={false}
                      message="The view in Unity Catalog was changed outside the app. Its current YAML is below. Promote replaces it."
                    />
                    <SqlBlock label="YAML in Unity Catalog now" sql={plan.ucYaml ?? ''} />
                    <Checkbox componentId="gsb.promote.overwrite" isChecked={overwrite} onChange={setOverwrite}>
                      Replace the changes made outside the app
                    </Checkbox>
                  </>
                )}
                {reviewing && <ImpactPanel path={`/api/projects/${projectId}/promotion/impact`} />}
                <SqlBlock label="SQL" sql={plan.statement} />
              </div>
            </Modal>
          )}
        </div>
      )}
    </DataState>
  );
}
