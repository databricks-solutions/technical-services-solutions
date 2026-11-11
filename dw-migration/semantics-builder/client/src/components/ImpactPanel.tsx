import { Alert, Table, TableCell, TableHeader, TableRow, Typography } from '@databricks/design-system';
import type { ConsumerKind, Impact } from '../../../shared/promote';
import { useResource } from '../api';
import { DataState } from './DataState';

const KIND: Record<ConsumerKind, { label: string; path?: (id: string) => string }> = {
  genie_space: { label: 'Genie space', path: (id) => `/genie/rooms/${id}` },
  dashboard: { label: 'Dashboard', path: (id) => `/dashboardsv3/${id}` },
  alert: { label: 'Alert', path: (id) => `/sql/alerts/${id}` },
  app: { label: 'App' },
  job: { label: 'Job', path: (id) => `/jobs/${id}` },
  pipeline: { label: 'Pipeline', path: (id) => `/pipelines/${id}` },
  notebook: { label: 'Notebook', path: (id) => `/#notebook/${id}` },
  query: { label: 'Query', path: (id) => `/sql/queries/${id}` },
  adhoc: { label: 'Ad hoc queries' },
};

const list = (label: string, names: string[]) =>
  names.length > 0 && (
    <li>
      {label}: {names.join(', ')}
    </li>
  );

/** In the Promote modal: the field changes against the view in Unity Catalog, and its consumers from lineage. */
export function ImpactPanel({ projectId }: { projectId: string }) {
  const data = useResource<Impact>(`/api/projects/${projectId}/promotion/impact`);
  const base = useResource<{ workspaceUrl: string | null }>('/api/config').data?.workspaceUrl;
  const v = data.data;
  const c = v?.changes;
  const breaking = new Set([...(c?.removed ?? []), ...(c?.renamed.map((r) => r.from) ?? [])]);
  const hit = v?.consumers?.filter((x) => x.uses.some((f) => breaking.has(f))) ?? [];
  const anyChange =
    c && (c.removed.length || c.renamed.length || c.changed.length || c.added.length || c.filterChanged);

  return (
    <DataState status={data.status} message={data.error} onRetry={data.reload}>
      {v && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <Typography.Title level={4} withoutMargins>
            Impact
          </Typography.Title>
          {c === null && v.consumers?.length === 0 && !v.error && (
            <Typography.Text>The view is not in Unity Catalog yet, so nobody uses it.</Typography.Text>
          )}
          {c && !anyChange && <Typography.Text>No field changes against the view in Unity Catalog.</Typography.Text>}
          {c && anyChange ? (
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {list('Removed', c.removed)}
              {list(
                'Renamed',
                c.renamed.map((r) => `${r.from} to ${r.to}`)
              )}
              {list('New expression', c.changed)}
              {list('Added', c.added)}
              {c.filterChanged && <li>The global filter changed, so every measure can change.</li>}
            </ul>
          ) : null}
          {hit.length > 0 && (
            <Alert
              componentId="gsb.impact.breaking"
              type="error"
              closable={false}
              message={`${hit.length === 1 ? '1 consumer queries' : `${hit.length} consumers query`} fields that this version removes or renames. Their queries fail after Promote.`}
            />
          )}
          {v.error && <Alert componentId="gsb.impact.error" type="info" closable={false} message={v.error} />}
          {v.consumers && v.consumers.length > 0 && (
            <>
              <Typography.Text color="secondary">
                Read in the last {v.days} days, from lineage. Lineage does not record every read, so this list can miss
                a consumer. Fields come from column lineage.
              </Typography.Text>
              <Table aria-label="Consumers">
                <TableRow isHeader>
                  <TableHeader componentId="gsb.impact.h_kind">Consumer</TableHeader>
                  <TableHeader componentId="gsb.impact.h_users">Users</TableHeader>
                  <TableHeader componentId="gsb.impact.h_queries">Queries</TableHeader>
                  <TableHeader componentId="gsb.impact.h_last">Last read</TableHeader>
                  <TableHeader componentId="gsb.impact.h_uses">Uses changed fields</TableHeader>
                </TableRow>
                {v.consumers.map((x) => {
                  const k = KIND[x.kind];
                  return (
                    <TableRow key={`${x.kind}-${x.id ?? ''}`}>
                      <TableCell>
                        {x.id && k.path && base ? (
                          <Typography.Link
                            componentId="gsb.impact.open"
                            href={`${base}${k.path(x.id)}`}
                            openInNewTab
                          >{`${k.label} ${x.id}`}</Typography.Link>
                        ) : (
                          `${k.label}${x.id ? ` ${x.id}` : ''}`
                        )}
                      </TableCell>
                      <TableCell>{x.users}</TableCell>
                      <TableCell>{x.queries}</TableCell>
                      <TableCell>{x.lastUsed ? new Date(x.lastUsed).toLocaleDateString() : ''}</TableCell>
                      <TableCell>
                        <span
                          style={{
                            color: x.uses.some((f) => breaking.has(f)) ? 'var(--db-alert-icon-color-error)' : undefined,
                          }}
                        >
                          {x.uses.join(', ') || 'None'}
                        </span>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </Table>
            </>
          )}
          {v.consumers?.length === 0 && c !== null && !v.error && (
            <Typography.Text>Nobody read the view in the last {v.days} days, by lineage.</Typography.Text>
          )}
        </div>
      )}
    </DataState>
  );
}
