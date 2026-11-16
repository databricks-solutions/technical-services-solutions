import { useState } from 'react';
import { Alert, Button, Tag, Typography } from '@databricks/design-system';
import { BI_COMPATIBILITY_SQL } from '../../../shared/bi';
import type { BiCheck } from '../../../shared/bi';
import { api, useResource } from '../api';
import { DataState } from './DataState';
import { SqlBlock } from './SqlBlock';
import { StatusLine } from './StatusLine';

/**
 * Connect Power BI or Tableau to the promoted view: the query shape they send, a check that runs it as you, and the
 * setup for each tool. A metric view needs MEASURE() for its measures, so a plain table connection does not work.
 */
export function BiPanel({ projectId }: { projectId: string }) {
  const res = useResource<BiCheck>(`/api/projects/${projectId}/bi`);
  const [checked, setChecked] = useState<BiCheck>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const c = checked ?? res.data;

  const run = () => {
    setBusy(true);
    setError(undefined);
    api<BiCheck>(`/api/projects/${projectId}/bi`, {}).then(
      (r) => {
        setBusy(false);
        setChecked(r);
      },
      (err: unknown) => {
        setBusy(false);
        setError((err as Error).message);
      }
    );
  };

  return (
    <DataState status={res.status} message={res.error} onRetry={res.reload}>
      {c && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Typography.Text color="secondary">
            BI tools read a metric view with SQL that uses MEASURE() for each measure. Paste the query below into Power
            BI (Native query, DirectQuery) or Tableau (Custom SQL), and change the fields. The check runs the same query
            as you, so it shows if your rights and the view work, before a BI developer tries.
          </Typography.Text>
          {!c.sql ? (
            <Typography.Text>Promote a version with a dimension and a measure first.</Typography.Text>
          ) : (
            <>
              <SqlBlock label={`Query for ${c.target} (version ${c.version})`} sql={c.sql} />
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <Button componentId="gsb.bi.check" type="primary" loading={busy} onClick={run}>
                  Run the check
                </Button>
                <Button componentId="gsb.bi.copy" onClick={() => void navigator.clipboard.writeText(c.sql ?? '')}>
                  Copy the query
                </Button>
              </div>
              {error && <Alert componentId="gsb.bi.error" type="error" closable={false} message={error} />}
              {c.result &&
                (c.result.status === 'passed' ? (
                  <StatusLine message={c.result.detail} />
                ) : (
                  <Alert componentId="gsb.bi.failed" type="error" closable={false} message={c.result.detail} />
                ))}
              <Typography.Title level={4} withoutMargins>
                Power BI
              </Typography.Title>
              <ul style={{ margin: 0, paddingLeft: 20 }}>
                <li>
                  In the Databricks connector, use DirectQuery and <Typography.Text bold>Native query</Typography.Text>{' '}
                  with the query above. BI compatibility mode is not available in the Power BI connector.
                </li>
                <li>
                  Publishing the metric view to Power BI as a semantic model is a Private Preview; ask your Databricks
                  team.{' '}
                  <Tag componentId="gsb.bi.preview" color="lemon">
                    Private Preview
                  </Tag>
                </li>
              </ul>
              <Typography.Title level={4} withoutMargins>
                Tableau
              </Typography.Title>
              <ul style={{ margin: 0, paddingLeft: 20 }}>
                <li>
                  Use <Typography.Text bold>Custom SQL</Typography.Text> with the query above.
                </li>
                <li>
                  Or, on a SQL warehouse, put this in <Typography.Text bold>Initial SQL</Typography.Text> to use the
                  view like a table: <code>{BI_COMPATIBILITY_SQL}</code> Then keep the aggregation of each measure on
                  SUM. Grand totals of ratios and distinct counts can be wrong, a measure cannot be in a group, and the
                  view cannot be joined with other tables.
                </li>
              </ul>
            </>
          )}
        </div>
      )}
    </DataState>
  );
}
