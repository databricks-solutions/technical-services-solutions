import { useState } from 'react';
import {
  Alert,
  Button,
  FormUI,
  Input,
  Modal,
  Table,
  TableCell,
  TableHeader,
  TableRow,
  Typography,
} from '@databricks/design-system';
import type { GovernView } from '../../../shared/govern';
import { api, useResource } from '../api';
import { DataState } from './DataState';
import { SqlBlock } from './SqlBlock';

type Action = 'owner' | 'grant' | 'revoke';
const WARN: Record<Action, string> = {
  grant: 'This gives read access to the view, as you.',
  revoke: 'This takes read access to the view away, as you.',
  owner:
    'This hands the view to a new owner, as you. Unless you are in the new owner group, you can no longer promote, grant or change the owner. Transfer before you add a materialization.',
};

/** Owner and read grants of the promoted view. Every change shows its one statement before it runs as the user. */
export function GovernPanel({ projectId }: { projectId: string }) {
  const data = useResource<GovernView>(`/api/projects/${projectId}/governance`);
  const [principal, setPrincipal] = useState('');
  const [review, setReview] = useState<{ action: Action; principal: string; statement: string }>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const v = data.data;

  const preview = (action: Action, who: string) => {
    setBusy(true);
    setError(undefined);
    api<{ statement: string }>(`/api/projects/${projectId}/governance/preview`, { action, principal: who }).then(
      (r) => {
        setBusy(false);
        setReview({ action, principal: who, statement: r.statement });
      },
      (err: unknown) => {
        setBusy(false);
        setError((err as Error).message);
      }
    );
  };
  const run = () => {
    if (!review) return;
    setBusy(true);
    api<GovernView>(`/api/projects/${projectId}/governance`, review).then(
      (next) => {
        setBusy(false);
        setReview(undefined);
        setPrincipal('');
        data.setData(next);
      },
      (err: unknown) => {
        setBusy(false);
        setReview(undefined);
        setError((err as Error).message);
      }
    );
  };

  return (
    <section aria-label="Owner and access" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Typography.Title level={4} withoutMargins>
        Owner and access
      </Typography.Title>
      <DataState status={data.status} message={data.error} onRetry={data.reload}>
        {v &&
          (v.problem ? (
            <Typography.Text color="secondary">{v.problem}</Typography.Text>
          ) : (
            <>
              <Typography.Text>
                Owner: <b>{v.owner ?? 'unknown'}</b>
                {v.youOwn ? ' (you)' : '. Only the owner can change access or the owner.'}
                {v.materialized ? ' The view has a materialization, so its owner cannot change.' : ''}
              </Typography.Text>
              {v.grants.length ? (
                <Table aria-label="Grants">
                  <TableRow isHeader>
                    <TableHeader componentId="gsb.govern.h_principal">Principal</TableHeader>
                    <TableHeader componentId="gsb.govern.h_privilege">Privilege</TableHeader>
                    <TableHeader componentId="gsb.govern.h_action"> </TableHeader>
                  </TableRow>
                  {v.grants.map((g) => (
                    <TableRow key={`${g.principal}:${g.privilege}`}>
                      <TableCell>{g.principal}</TableCell>
                      <TableCell>{g.privilege}</TableCell>
                      <TableCell>
                        {v.youOwn && g.privilege === 'SELECT' && (
                          <Button
                            componentId="gsb.govern.revoke"
                            size="small"
                            disabled={busy}
                            onClick={() => preview('revoke', g.principal)}
                          >
                            Revoke
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </Table>
              ) : (
                <Typography.Text color="secondary">
                  No direct grants on the view. Access can still come from the schema or catalog.
                </Typography.Text>
              )}
              {v.youOwn && (
                <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
                  <div style={{ minWidth: 320 }}>
                    <FormUI.Label htmlFor="gv-principal">User, group or service principal</FormUI.Label>
                    <Input
                      componentId="gsb.govern.principal"
                      id="gv-principal"
                      placeholder="analysts or name@example.com"
                      value={principal}
                      onChange={(e) => setPrincipal(e.target.value)}
                    />
                  </div>
                  <Button
                    componentId="gsb.govern.grant"
                    disabled={busy || !principal.trim()}
                    onClick={() => preview('grant', principal.trim())}
                  >
                    Grant read access
                  </Button>
                  <Button
                    componentId="gsb.govern.owner"
                    disabled={busy || !principal.trim() || v.materialized}
                    onClick={() => preview('owner', principal.trim())}
                  >
                    Transfer ownership
                  </Button>
                </div>
              )}
            </>
          ))}
      </DataState>
      {error && <Alert componentId="gsb.govern.error" type="error" closable={false} message={error} />}
      {review && (
        <Modal
          componentId="gsb.govern.modal"
          title={
            review.action === 'owner'
              ? 'Transfer ownership'
              : review.action === 'grant'
                ? 'Grant read access'
                : 'Revoke read access'
          }
          visible
          okText="Run SQL"
          cancelText="Cancel"
          okButtonProps={{ loading: busy }}
          onCancel={() => setReview(undefined)}
          onOk={run}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <Alert
              componentId="gsb.govern.warning"
              type={review.action === 'owner' ? 'error' : 'warning'}
              closable={false}
              message={WARN[review.action]}
            />
            <SqlBlock label="SQL" sql={review.statement} />
          </div>
        </Modal>
      )}
    </section>
  );
}
