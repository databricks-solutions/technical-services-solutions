import { useState } from 'react';
import { Alert, Button, SparkleIcon, Spinner, Tag, Typography } from '@databricks/design-system';
import type { RelationCheck } from '../../../shared/readiness';
import { api } from '../api';
import { TablePicker } from './UcPicker';

const short = (t: string) => t.split('.').pop() ?? t;

function CheckResult({ check }: { check: RelationCheck }) {
  const [main, ...rest] = check.groups;
  const outside = rest.flat();
  const reason = new Map(check.ai?.tables.map((t) => [t.table.toLowerCase(), t]) ?? []);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <Alert
        componentId="gsb.selector.check"
        type={outside.length ? 'warning' : 'success'}
        closable={false}
        message={
          outside.length
            ? `${outside.length} table${outside.length === 1 ? ' does' : 's do'} not join to the main group`
            : `All ${main.length} tables join together`
        }
        description={check.ai?.summary}
      />
      {check.links.length > 0 && (
        <div>
          <Typography.Text bold>Joins found from the key names</Typography.Text>
          <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
            {check.links.map((l) => (
              <li key={`${l.from}.${l.column}`}>
                <code>
                  {short(l.from)}.{l.column}
                </code>{' '}
                to{' '}
                <code>
                  {short(l.to)}.{l.refColumn}
                </code>
              </li>
            ))}
          </ul>
        </div>
      )}
      {outside.length > 0 && (
        <div>
          <Typography.Text bold>Tables outside the main group</Typography.Text>
          <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
            {outside.map((t) => (
              <li key={t}>
                {t}
                {reason.get(t)?.reason ? `: ${reason.get(t)?.reason}` : ''}
              </li>
            ))}
          </ul>
        </div>
      )}
      {check.ai?.suggestion && (
        <Typography.Text>
          <SparkleIcon /> <Typography.Text bold>Suggestion: </Typography.Text>
          {check.ai.suggestion}
        </Typography.Text>
      )}
      {check.ai && (
        <Typography.Text color="secondary" size="sm">
          Joins come from rules on the key names. The explanation is AI. Check it against your knowledge of the data.
        </Typography.Text>
      )}
      {check.aiError && (
        <Typography.Text color="secondary" size="sm">
          The AI explanation is not available now. The joins above are still valid.
        </Typography.Text>
      )}
    </div>
  );
}

/** Pick tables, check how they relate to each other and to the current sources, then add them. */
export function TableSelector({
  projectId,
  addLabel,
  onAdd,
}: {
  projectId: string;
  addLabel: (n: number) => string;
  onAdd: (tables: string[]) => Promise<void>;
}) {
  const [picked, setPicked] = useState<string[]>([]);
  const [check, setCheck] = useState<RelationCheck>();
  const [busy, setBusy] = useState<'check' | 'add'>();
  const [error, setError] = useState<string>();
  const outside = new Set(check?.groups.slice(1).flat() ?? []);
  const joined = picked.filter((t) => !outside.has(t.toLowerCase()));

  const pick = (tables: string[]) => {
    setPicked(tables);
    setCheck(undefined);
  };
  const runCheck = () => {
    setBusy('check');
    setError(undefined);
    api<RelationCheck>(`/api/projects/${projectId}/sources/check`, { tables: picked }).then(
      (c) => {
        setBusy(undefined);
        setCheck(c);
      },
      (err: unknown) => {
        setBusy(undefined);
        setError((err as Error).message);
      }
    );
  };
  const add = (tables: string[]) => {
    setBusy('add');
    void onAdd(tables).finally(() => setBusy(undefined));
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <TablePicker value={picked} onChange={pick} />
      {error && <Alert componentId="gsb.selector.error" type="error" closable={false} message={error} />}
      {busy === 'check' && (
        <div role="status" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <Spinner label="Checking" />
          <Typography.Text color="secondary">Checking how the tables join. This takes a few seconds.</Typography.Text>
        </div>
      )}
      {check && <CheckResult check={check} />}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        {!check ? (
          <Button
            componentId="gsb.selector.check_button"
            type="primary"
            disabled={!picked.length || !!busy}
            onClick={runCheck}
          >
            Check how they relate
          </Button>
        ) : (
          <>
            <Button
              componentId="gsb.selector.add"
              type="primary"
              loading={busy === 'add'}
              disabled={!!busy || !(outside.size ? joined.length : picked.length)}
              onClick={() => add(outside.size ? joined : picked)}
            >
              {addLabel(outside.size ? joined.length : picked.length)}
            </Button>
            {outside.size > 0 && (
              <Button componentId="gsb.selector.add_all" disabled={!!busy} onClick={() => add(picked)}>
                Add all {picked.length} anyway
              </Button>
            )}
          </>
        )}
        {picked.length > 0 && (
          <Tag componentId="gsb.selector.count">
            {picked.length} table{picked.length === 1 ? '' : 's'} selected
          </Tag>
        )}
      </div>
    </div>
  );
}
