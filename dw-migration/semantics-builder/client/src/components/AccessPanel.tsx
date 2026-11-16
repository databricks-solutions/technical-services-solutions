import { useState } from 'react';
import { Alert, Button, Table, TableCell, TableHeader, TableRow, Tag, Typography } from '@databricks/design-system';
import { accessDifference } from '../../../shared/access';
import type { AccessDifference, AccessResult, AccessView } from '../../../shared/access';
import { api, useResource } from '../api';
import { DataState } from './DataState';

const DIFF: Record<AccessDifference, { label: string; color?: 'lemon' | 'coral' } | null> = {
  same: null,
  no_owner_run: null,
  fewer_rows: { label: 'Fewer rows than the owner', color: 'lemon' },
  more_rows: { label: 'More rows than the owner', color: 'lemon' },
  other_value: { label: 'Other value than the owner', color: 'lemon' },
  fails: { label: 'Fails', color: 'coral' },
};

/**
 * The tests of the promoted view, run as you. As the owner you see every person who ran them on the same version;
 * as a reviewer you see your own run. Fewer rows or other values mean a row filter or a column mask is at work.
 */
export function AccessPanel({ path, asOwner }: { path: string; asOwner: boolean }) {
  const res = useResource<AccessView>(path);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const v = res.data;

  const run = () => {
    setBusy(true);
    setError(undefined);
    api<AccessView>(path, {}).then(
      (next) => {
        setBusy(false);
        res.setData(next);
      },
      (err: unknown) => {
        setBusy(false);
        setError((err as Error).message);
      }
    );
  };

  const owner = v?.runs.find((r) => r.isOwner);
  const cell = (r: AccessResult | undefined, base: AccessResult | undefined, isOwner: boolean) => {
    if (!r) return <Typography.Text color="secondary">Not run</Typography.Text>;
    const d = isOwner ? null : DIFF[accessDifference(base, r)];
    return (
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
        {r.detail}
        {d && (
          <Tag componentId="gsb.access.diff" color={d.color}>
            {d.label}
          </Tag>
        )}
      </div>
    );
  };

  return (
    <section aria-label="Access check" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Typography.Title level={4} withoutMargins>
        Access check
      </Typography.Title>
      <DataState status={res.status} message={res.error} onRetry={res.reload}>
        {v &&
          (v.problem || !v.target ? (
            <Typography.Text color="secondary">{v.problem}</Typography.Text>
          ) : (
            <>
              <Typography.Text color="secondary">
                {asOwner
                  ? `Run the ${v.tests} tests of version ${v.version} on ${v.target} as you, then ask a person with less access to run them too: request a review from that person, and they click Run the tests as me in the review. Row filters show as fewer rows, column masks as other values, and a missing grant as a failure. The app keeps the status and the row counts only.`
                  : `Run the ${v.tests} tests of version ${v.version} on ${v.target} as you. The owner sees if you get fewer rows or other values, which shows that row filters and column masks work. The app keeps the status and the row counts only, not the values.`}
              </Typography.Text>
              <div>
                <Button componentId="gsb.access.run" type="primary" loading={busy} onClick={run}>
                  Run the tests as me
                </Button>
              </div>
              {v.runs.length > 0 && (
                <Table aria-label="Access check results" scrollable>
                  <TableRow isHeader>
                    <TableHeader componentId="gsb.access.h_test">Test</TableHeader>
                    {v.runs.map((r) => (
                      <TableHeader key={r.runBy} componentId="gsb.access.h_person" style={{ flex: 2 }}>
                        {r.runBy}
                        {r.isOwner ? ' (owner)' : ''}, {new Date(r.createdAt).toLocaleString()}
                      </TableHeader>
                    ))}
                  </TableRow>
                  {(v.runs[0]?.results ?? []).map((t) => (
                    <TableRow key={t.name}>
                      <TableCell>{t.name}</TableCell>
                      {v.runs.map((r) => (
                        <TableCell key={r.runBy} multiline style={{ flex: 2 }}>
                          {cell(
                            r.results.find((x) => x.name === t.name),
                            owner?.results.find((x) => x.name === t.name),
                            r.isOwner
                          )}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </Table>
              )}
            </>
          ))}
      </DataState>
      {error && <Alert componentId="gsb.access.error" type="error" closable={false} message={error} />}
    </section>
  );
}
