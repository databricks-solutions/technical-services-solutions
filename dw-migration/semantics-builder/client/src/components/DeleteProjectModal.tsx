import { useState } from 'react';
import { Checkbox, DangerModal, FormUI, Input, Spinner, Typography } from '@databricks/design-system';
import type { DeletePlan } from '../../../shared/brief';
import { api, useResource } from '../api';
import { MONO } from './SqlBlock';

/**
 * Deletes a project or sub-project after the user reviews what goes. A project with
 * sub-projects asks for its name. Sandbox views are dropped first, as the user, by default.
 */
export function DeleteProjectModal({
  projectId,
  kind,
  onClose,
  onDeleted,
}: {
  projectId: string;
  kind: 'project' | 'sub-project';
  onClose: () => void;
  onDeleted: () => void;
}) {
  const plan = useResource<DeletePlan>(`/api/projects/${projectId}/delete`);
  const [drop, setDrop] = useState(true);
  const [typed, setTyped] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const p = plan.data;
  const needName = !!p?.subProjects.length;
  const ready = !!p && (!needName || typed.trim() === p.name);

  const submit = () => {
    if (!p) return;
    setBusy(true);
    setError(undefined);
    api(`/api/projects/${projectId}/delete`, { cleanup: drop ? p.cleanup : [] }).then(onDeleted, (err: unknown) => {
      setBusy(false);
      setError((err as Error).message);
    });
  };

  return (
    <DangerModal
      componentId="gsb.projects.delete_modal"
      title={p ? `Delete ${kind} "${p.name}"?` : `Delete ${kind}?`}
      visible
      okText={`Delete ${kind}`}
      okButtonProps={{ disabled: !ready, loading: busy }}
      cancelText="Cancel"
      onOk={submit}
      onCancel={onClose}
    >
      {plan.status === 'loading' && <Spinner label="Loading" />}
      {plan.status === 'error' && <FormUI.Message type="error" message={plan.error ?? 'Could not load the project.'} />}
      {p && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Typography.Text>
            This removes the brief, sources, designs, validations and pattern runs from the app. It cannot be undone.
            Your Unity Catalog tables do not change. The audit log keeps a record of the delete.
          </Typography.Text>
          {needName && (
            <div>
              <Typography.Text bold>
                Its {p.subProjects.length} sub-project{p.subProjects.length === 1 ? ' is' : 's are'} deleted too:
              </Typography.Text>
              <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
                {p.subProjects.map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
            </div>
          )}
          {p.cleanup.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <Checkbox componentId="gsb.projects.delete_drop" isChecked={drop} onChange={setDrop}>
                Also drop {p.cleanup.length} sandbox view{p.cleanup.length === 1 ? '' : 's'} (recommended). This SQL
                runs as you:
              </Checkbox>
              <pre
                style={{
                  ...MONO,
                  margin: 0,
                  padding: 8,
                  maxHeight: 160,
                  overflow: 'auto',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  border: '1px solid var(--db-border-base)',
                  borderRadius: 4,
                  opacity: drop ? 1 : 0.5,
                }}
              >
                {p.cleanup.map((s) => `${s};`).join('\n')}
              </pre>
              {!drop && (
                <Typography.Text color="secondary" size="sm">
                  The views stay in the sandbox schema. You can drop them later in Catalog Explorer.
                </Typography.Text>
              )}
            </div>
          )}
          {needName && (
            <div>
              <FormUI.Label htmlFor="gsb-delete-name">Type {p.name} to confirm</FormUI.Label>
              <Input
                componentId="gsb.projects.delete_name"
                id="gsb-delete-name"
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                autoComplete="off"
              />
            </div>
          )}
          {error && <FormUI.Message type="error" message={error} />}
        </div>
      )}
    </DangerModal>
  );
}
