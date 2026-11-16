import { useState } from 'react';
import { SimpleSelect, SimpleSelectOption, Typography } from '@databricks/design-system';
import type { DiffLine, VersionDiff } from '../../../shared/diff';
import { useResource } from '../api';
import { DataState } from './DataState';

const MARK: Record<DiffLine['kind'], { sign: string; background?: string }> = {
  same: { sign: ' ' },
  removed: { sign: '-', background: 'var(--db-negative-surface-subtle)' },
  added: { sign: '+', background: 'var(--db-positive-surface-subtle)' },
};

const item = (label: string, names: string[]) =>
  names.length > 0 && (
    <li>
      {label}: {names.join(', ')}
    </li>
  );

function Diff({ projectId, from, to }: { projectId: string; from: number; to: number }) {
  const res = useResource<VersionDiff>(`/api/projects/${projectId}/designs/compare?from=${from}&to=${to}`);
  const d = res.data;
  const c = d?.changes;
  const lines = d?.lines.filter((l) => l.kind !== 'same').length ?? 0;
  return (
    <DataState status={res.status} message={res.error} onRetry={res.reload}>
      {d && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {!lines ? (
            <Typography.Text>The two versions have the same YAML.</Typography.Text>
          ) : (
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {c === null && <li>One of the versions does not parse, so only the YAML lines are compared.</li>}
              {c && item('Removed', c.removed)}
              {c &&
                item(
                  'Renamed',
                  c.renamed.map((r) => `${r.from} to ${r.to}`)
                )}
              {c && item('New expression', c.changed)}
              {c && item('Added', c.added)}
              {c?.filterChanged && <li>The global filter changed.</li>}
              {item('Tests added', d.tests.added)}
              {item('Tests removed', d.tests.removed)}
              <li>
                {lines} YAML {lines === 1 ? 'line' : 'lines'} changed.
              </li>
            </ul>
          )}
          <pre
            aria-label={`YAML diff of version ${from} and version ${to}`}
            style={{
              margin: 0,
              maxHeight: 480,
              overflow: 'auto',
              fontSize: 12,
              border: '1px solid var(--db-border-base)',
              borderRadius: 4,
            }}
          >
            {d.lines.map((l, i) => (
              <div key={i} style={{ background: MARK[l.kind].background, padding: '0 8px', whiteSpace: 'pre' }}>
                {MARK[l.kind].sign} {l.text}
              </div>
            ))}
          </pre>
        </div>
      )}
    </DataState>
  );
}

/** Compare any two versions: field changes, test changes and a line diff of the YAML. */
export function VersionCompare({ projectId, versions }: { projectId: string; versions: number[] }) {
  const sorted = [...versions].sort((a, b) => b - a);
  const [to, setTo] = useState(sorted[0]);
  const [from, setFrom] = useState(sorted[1] ?? sorted[0]);
  if (sorted.length < 2) return null;
  const pick = (id: string, label: string, value: number, set: (v: number) => void) => (
    <SimpleSelect
      componentId={`gsb.designer.compare_${id}`}
      id={`compare-${id}`}
      label={label}
      value={String(value)}
      onChange={(e) => set(Number(e.target.value))}
    >
      {sorted.map((v) => (
        <SimpleSelectOption key={v} value={String(v)}>
          Version {v}
        </SimpleSelectOption>
      ))}
    </SimpleSelect>
  );
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <Typography.Title level={4} withoutMargins>
        Compare versions
      </Typography.Title>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        {pick('from', 'From', from, setFrom)}
        {pick('to', 'To', to, setTo)}
      </div>
      {from === to ? (
        <Typography.Text color="secondary">Select two different versions.</Typography.Text>
      ) : (
        <Diff key={`${from}-${to}`} projectId={projectId} from={from} to={to} />
      )}
    </div>
  );
}
