import { useState } from 'react';
import {
  Alert,
  Button,
  Checkbox,
  FormUI,
  Input,
  Modal,
  SimpleSelect,
  SimpleSelectOption,
  Tag,
  Typography,
} from '@databricks/design-system';
import type { AgentView, Principal } from '../../../shared/agent';
import { api, useResource } from '../api';
import { DataState } from './DataState';
import { SqlBlock } from './SqlBlock';

/**
 * The production Genie agent of a project: one Genie space on the promoted views of the chosen sub-projects, and the
 * command that gives the audience CAN RUN.
 */
export function AgentPanel({ projectId }: { projectId: string }) {
  const res = useResource<AgentView>(`/api/projects/${projectId}/agent`);
  const base = useResource<{ workspaceUrl: string | null }>('/api/config').data?.workspaceUrl;
  const [busy, setBusy] = useState<string>();
  const [error, setError] = useState<string>();
  const [picked, setPicked] = useState<string[]>();
  const [config, setConfig] = useState<string>();
  const [kind, setKind] = useState<Principal['kind']>('group');
  const [name, setName] = useState('');
  const [principals, setPrincipals] = useState<Principal[]>([]);
  const [command, setCommand] = useState<string>();
  const v = res.data;
  const chosen = picked ?? v?.agent?.subProjects ?? v?.candidates.map((c) => c.projectId) ?? [];
  const changedChoice = !!v?.agent && [...chosen].sort().join() !== [...v.agent.subProjects].sort().join();

  const post = <T,>(key: string, path: string, body: unknown, then: (r: T) => void) => {
    setBusy(key);
    setError(undefined);
    api<T>(`/api/projects/${projectId}/${path}`, body).then(
      (r) => {
        setBusy(undefined);
        then(r);
      },
      (err: unknown) => {
        setBusy(undefined);
        setError((err as Error).message);
      }
    );
  };

  return (
    <DataState status={res.status} message={res.error} onRetry={res.reload}>
      {v && (
        <section
          aria-label="Genie agent"
          style={{
            border: '1px solid var(--db-border-base)',
            borderRadius: 8,
            padding: 16,
            display: 'flex',
            flexDirection: 'column',
            gap: 12,
          }}
        >
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <Typography.Title level={3} withoutMargins>
              Genie agent
            </Typography.Title>
            {v.agent && (
              <Tag componentId="gsb.agent.current" color={v.agent.current && !changedChoice ? 'teal' : 'lemon'}>
                {v.agent.current && !changedChoice ? 'Up to date' : 'Update it'}
              </Tag>
            )}
            {v.agent && base && (
              <Typography.Link
                componentId="gsb.agent.open"
                href={`${base}/genie/rooms/${v.agent.spaceId}`}
                openInNewTab
              >
                Open in Genie
              </Typography.Link>
            )}
          </div>
          <Typography.Text color="secondary">
            One Genie space for the audience of this project, on the promoted views of the sub-projects you choose.
            Choose related sub-projects, so Genie can answer across them. Each view brings the brief, the tests, entity
            matching and the changes that Optimize with benchmarks kept. You create it as you, and you own it.
          </Typography.Text>
          {v.candidates.length === 0 ? (
            <Typography.Text>Promote the view of a sub-project first.</Typography.Text>
          ) : (
            <>
              <div
                role="group"
                aria-label="Sub-projects in the agent"
                style={{ display: 'flex', flexDirection: 'column', gap: 6 }}
              >
                {v.candidates.map((c) => (
                  <Checkbox
                    key={c.projectId}
                    componentId="gsb.agent.sub"
                    isChecked={chosen.includes(c.projectId)}
                    onChange={(on) =>
                      setPicked(on ? [...chosen, c.projectId] : chosen.filter((id) => id !== c.projectId))
                    }
                  >
                    {c.name}: <span style={{ wordBreak: 'break-all' }}>{c.view}</span>, version {c.version}
                    {c.kept ? `, ${c.kept} kept change${c.kept === 1 ? '' : 's'}` : ''}
                  </Checkbox>
                ))}
              </div>
              {(!v.agent || !v.agent.current || changedChoice) && (
                <div>
                  <Button
                    componentId="gsb.agent.examine"
                    type="primary"
                    loading={busy === 'examine'}
                    disabled={!chosen.length}
                    onClick={() =>
                      post<{ config: string }>('examine', 'agent', { subProjects: chosen }, (r) => setConfig(r.config))
                    }
                  >
                    {v.agent ? 'Update the Genie agent' : 'Create the Genie agent'}
                  </Button>
                </div>
              )}
            </>
          )}

          {v.agent && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <Typography.Title level={4} withoutMargins>
                Give the audience access
              </Typography.Title>
              <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
                <div style={{ width: 140 }}>
                  <SimpleSelect
                    componentId="gsb.agent.kind"
                    id="agent-kind"
                    label="Kind"
                    value={kind}
                    onChange={(e) => setKind(e.target.value as Principal['kind'])}
                  >
                    <SimpleSelectOption value="group">Group</SimpleSelectOption>
                    <SimpleSelectOption value="user">User</SimpleSelectOption>
                  </SimpleSelect>
                </div>
                <div style={{ minWidth: 260 }}>
                  <FormUI.Label htmlFor="agent-name">{kind === 'user' ? 'Email' : 'Group name'}</FormUI.Label>
                  <Input
                    componentId="gsb.agent.name"
                    id="agent-name"
                    value={name}
                    maxLength={320}
                    onChange={(e) => setName(e.target.value)}
                  />
                </div>
                <Button
                  componentId="gsb.agent.add"
                  disabled={!name.trim()}
                  onClick={() => {
                    setPrincipals((p) => [...p, { kind, name: name.trim() }]);
                    setName('');
                  }}
                >
                  Add
                </Button>
              </div>
              {principals.length > 0 && (
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                  {principals.map((p, i) => (
                    <Tag
                      key={`${p.kind}:${p.name}`}
                      componentId="gsb.agent.principal"
                      closable
                      onClose={() => setPrincipals((x) => x.filter((_, j) => j !== i))}
                    >
                      {p.kind === 'group' ? 'Group' : 'User'}: {p.name}
                    </Tag>
                  ))}
                  <Button
                    componentId="gsb.agent.command"
                    loading={busy === 'command'}
                    onClick={() =>
                      post<{ command: string }>('command', 'agent/access', { principals }, (r) => setCommand(r.command))
                    }
                  >
                    Make the CAN RUN command
                  </Button>
                </div>
              )}
              {command && (
                <>
                  <SqlBlock label="Run this in your terminal, as you (add --profile if you use one)" sql={command} />
                  <div>
                    <Button
                      componentId="gsb.agent.copy"
                      size="small"
                      onClick={() => void navigator.clipboard.writeText(command)}
                    >
                      Copy the command
                    </Button>
                  </div>
                </>
              )}
              <Typography.Text color="secondary" size="sm">
                The app cannot change who can use a Genie space: apps cannot get that permission scope. Run the command
                with the Databricks CLI, or use Share in Genie. CAN RUN lets a person ask the agent. Genie runs each
                query as that person, so they also need SELECT on each promoted view (Governance of each sub-project)
                and CAN USE on the SQL warehouse.
              </Typography.Text>
            </div>
          )}
          {error && <Alert componentId="gsb.agent.error" type="error" closable={false} message={error} />}

          <Modal
            componentId="gsb.agent.modal"
            title={v.agent ? 'Update the Genie agent' : 'Create the Genie agent'}
            visible={!!config}
            okText={v.agent ? 'Update the agent' : 'Create the agent'}
            cancelText="Cancel"
            okButtonProps={{ loading: busy === 'save' }}
            onCancel={() => setConfig(undefined)}
            onOk={() =>
              post<AgentView>('save', 'agent', { subProjects: chosen, config }, (next) => {
                setConfig(undefined);
                setPicked(undefined);
                res.setData(next);
              })
            }
          >
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <Alert
                componentId="gsb.agent.warning"
                type="warning"
                closable={false}
                message={
                  v.agent
                    ? 'This replaces all the settings of the agent, as you. Changes made in Genie are lost.'
                    : 'This creates a Genie space in your workspace folder, as you.'
                }
              />
              {config && <SqlBlock label="Genie space settings (JSON)" sql={config} />}
            </div>
          </Modal>
        </section>
      )}
    </DataState>
  );
}
