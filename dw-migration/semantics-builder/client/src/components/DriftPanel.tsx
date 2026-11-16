import { useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import {
  Alert,
  Button,
  Checkbox,
  Table,
  TableCell,
  TableHeader,
  TableRow,
  Tag,
  Typography,
} from '@databricks/design-system';
import type { DriftFix, DriftSeverity, DriftView } from '../../../shared/drift';
import { api, useResource } from '../api';
import { subPath } from '../pages/ProjectsPage';
import { DataState } from './DataState';

const SEVERITY: Record<DriftSeverity, { color: 'coral' | 'lemon' | 'default'; label: string }> = {
  error: { color: 'coral', label: 'Error' },
  warning: { color: 'lemon', label: 'Warning' },
  info: { color: 'default', label: 'Info' },
};
const FIX: Record<Exclude<DriftFix, null>, { label: string; module: string | null }> = {
  promote: { label: 'Restore or promote', module: null },
  designer: { label: 'Open the designer', module: 'designer' },
  readiness: { label: 'Open the sources', module: 'sources' },
  materialize: { label: 'Open Optimize', module: 'optimize' },
};

/** Drift of the promoted view: schema, definition, governance, usage and opt-in data drift, checked as the user. */
export function DriftPanel({ projectId }: { projectId: string }) {
  const { parentId = '' } = useParams();
  const navigate = useNavigate();
  const data = useResource<DriftView>(`/api/projects/${projectId}/drift`);
  const [busy, setBusy] = useState<string>();
  const [error, setError] = useState<string>();
  const v = data.data;

  const post = (key: string, path: string, body: unknown) => {
    setBusy(key);
    setError(undefined);
    api<DriftView>(path, body).then(
      (next) => {
        setBusy(undefined);
        data.setData(next);
      },
      (err: unknown) => {
        setBusy(undefined);
        setError((err as Error).message);
      }
    );
  };

  return (
    <section aria-label="Drift" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Typography.Title level={4} withoutMargins>
        Drift
      </Typography.Title>
      <DataState status={data.status} message={data.error} onRetry={data.reload}>
        {v &&
          (v.problem ? (
            <Typography.Text color="secondary">{v.problem}</Typography.Text>
          ) : (
            <>
              <Typography.Text color="secondary">
                Compares the view in Unity Catalog with its promoted version, its sources, its owner and grants, and its
                materialization, as you.
              </Typography.Text>
              <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
                <Button
                  componentId="gsb.drift.check"
                  type="primary"
                  loading={busy === 'check'}
                  disabled={!!busy}
                  onClick={() => post('check', `/api/projects/${projectId}/drift/check`, {})}
                >
                  Check drift
                </Button>
                <Checkbox
                  componentId="gsb.drift.baseline"
                  isChecked={!!v.baseline}
                  disabled={!!busy}
                  onChange={(on) => post('baseline', `/api/projects/${projectId}/drift/baseline`, { enable: on })}
                >
                  Track measure totals (data drift)
                </Checkbox>
              </div>
              <Typography.Text color="secondary" size="sm">
                {v.baseline
                  ? `Baseline of ${v.baseline.measures} measure totals, set by ${v.baseline.by} on ${new Date(v.baseline.at).toLocaleString()}. The app stores these totals, and no other result values. Clear the box to delete them.`
                  : 'Data drift is off. When on, the app stores the total of each measure once, and compares later checks with it.'}
              </Typography.Text>
              {v.last && (
                <>
                  <Typography.Text>
                    Last check by {v.last.createdBy} on {new Date(v.last.createdAt).toLocaleString()}.
                  </Typography.Text>
                  <Table aria-label="Drift findings" scrollable>
                    <TableRow isHeader>
                      <TableHeader componentId="gsb.drift.h_severity">Severity</TableHeader>
                      <TableHeader componentId="gsb.drift.h_kind">Kind</TableHeader>
                      <TableHeader componentId="gsb.drift.h_finding">Finding</TableHeader>
                      <TableHeader componentId="gsb.drift.h_fix">Fix</TableHeader>
                    </TableRow>
                    {v.last.findings.map((f, i) => (
                      // Findings have no id; their order is fixed for one check.
                      // eslint-disable-next-line react/no-array-index-key
                      <TableRow key={i}>
                        <TableCell>
                          <Tag componentId="gsb.drift.severity" color={SEVERITY[f.severity].color}>
                            {SEVERITY[f.severity].label}
                          </Tag>
                        </TableCell>
                        <TableCell>{f.kind}</TableCell>
                        <TableCell>
                          <div style={{ display: 'flex', flexDirection: 'column' }}>
                            <Typography.Text bold>{f.title}</Typography.Text>
                            <Typography.Text>{f.detail}</Typography.Text>
                          </div>
                        </TableCell>
                        <TableCell>
                          {f.fix &&
                            (FIX[f.fix].module ? (
                              <Button
                                componentId="gsb.drift.fix"
                                size="small"
                                onClick={() => void navigate(subPath(parentId, projectId, FIX[f.fix!].module!))}
                              >
                                {FIX[f.fix].label}
                              </Button>
                            ) : (
                              <Typography.Text color="secondary">
                                {FIX[f.fix].label}, on this tab or in History
                              </Typography.Text>
                            ))}
                        </TableCell>
                      </TableRow>
                    ))}
                  </Table>
                  {v.history.length > 1 && (
                    <Typography.Text color="secondary" size="sm">
                      Earlier checks:{' '}
                      {v.history
                        .slice(1, 6)
                        .map(
                          (h) =>
                            `${new Date(h.createdAt).toLocaleDateString()} (${h.errors} errors, ${h.warnings} warnings)`
                        )
                        .join('; ')}
                    </Typography.Text>
                  )}
                </>
              )}
            </>
          ))}
      </DataState>
      {error && <Alert componentId="gsb.drift.error" type="error" closable={false} message={error} />}
    </section>
  );
}
