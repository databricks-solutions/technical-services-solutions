import { useState } from 'react';
import { Alert, Button, FormUI, Input, Typography } from '@databricks/design-system';
import { dashboardCommand, validFolder } from '../../../shared/dashboard';
import type { DashboardView } from '../../../shared/dashboard';
import { useResource } from '../api';
import { DataState } from './DataState';
import { SqlBlock } from './SqlBlock';

/** A starter AI/BI dashboard on the promoted view, and the command that creates it as a draft, as you. */
export function DashboardPanel({ projectId }: { projectId: string }) {
  const res = useResource<DashboardView>(`/api/projects/${projectId}/dashboard`);
  const [folder, setFolder] = useState<string>();
  const v = res.data;
  const where = (folder ?? v?.folder ?? '').trim();
  const ok = validFolder(where);
  const command = v?.plan && v.warehouseId && ok ? dashboardCommand(v.name, v.warehouseId, where, v.plan.json) : null;

  return (
    <DataState status={res.status} message={res.error} onRetry={res.reload}>
      {v && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Typography.Text color="secondary">
            A starter AI/BI dashboard on the promoted view: KPIs for the first measures, a trend by month, and a
            breakdown by the first text dimension. Every number comes from the governed measures of the view. Apps
            cannot get the permission scope of the dashboards API, so run the command below in your terminal, as you,
            with the Databricks CLI. It creates a draft. You review it and publish it in Databricks.
          </Typography.Text>
          {!v.plan ? (
            <Typography.Text>Promote a version first.</Typography.Text>
          ) : (
            <>
              <Typography.Text>
                Version {v.promoted?.version}. KPIs: {v.plan.kpis.join(', ') || 'none'}. Trend:{' '}
                {v.plan.trend ?? 'no date dimension'}. Breakdown: {v.plan.breakdown ?? 'no text dimension'}.
              </Typography.Text>
              <div style={{ minWidth: 360, maxWidth: 560 }}>
                <FormUI.Label htmlFor="dash-folder">Folder (it must exist)</FormUI.Label>
                <Input
                  componentId="gsb.dash.folder"
                  id="dash-folder"
                  value={where}
                  onChange={(e) => setFolder(e.target.value)}
                />
                {!ok && <FormUI.Message type="error" message='Use a folder under /Users or /Shared, with no "..".' />}
              </div>
              {!v.warehouseId && (
                <Alert
                  componentId="gsb.dash.no_wh"
                  type="warning"
                  closable={false}
                  message="The app has no SQL warehouse."
                />
              )}
              {command && (
                <>
                  <SqlBlock label="Command (add --profile if you use one)" sql={command} />
                  <div>
                    <Button componentId="gsb.dash.copy" onClick={() => void navigator.clipboard.writeText(command)}>
                      Copy the command
                    </Button>
                  </div>
                </>
              )}
              <SqlBlock label="Dashboard (JSON)" sql={v.plan.json} />
            </>
          )}
        </div>
      )}
    </DataState>
  );
}
