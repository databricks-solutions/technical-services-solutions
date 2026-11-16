import { Alert, Table, TableCell, TableHeader, TableRow, Tag, Typography } from '@databricks/design-system';
import type { UsageView } from '../../../shared/usage';
import { useResource } from '../api';
import { DataState } from './DataState';

const TOP = 3;

/**
 * Which fields of the promoted view people really query, from Unity Catalog lineage, read as you. Fields that nobody
 * read are candidates to remove; the most used measures are candidates to materialize.
 */
export function UsagePanel({ projectId }: { projectId: string }) {
  const res = useResource<UsageView>(`/api/projects/${projectId}/optimize/usage`);
  const u = res.data;
  const unused = u?.fields.filter((f) => !f.queries && !f.usedBy.length) ?? [];
  const top = u?.fields.filter((f) => f.kind === 'measure' && f.queries > 0).slice(0, TOP) ?? [];

  return (
    <DataState status={res.status} message={res.error} onRetry={res.reload}>
      {u && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Typography.Text color="secondary">
            How people used the fields of the view in Unity Catalog in the last {u.days} days, from the lineage tables,
            as you. The app shows counts only: no user names and no query text. Genie, dashboards, jobs and SQL all
            count.
          </Typography.Text>
          {!u.target ? (
            <Typography.Text>Promote a version first. Usage is about the view that people query.</Typography.Text>
          ) : (
            <>
              {u.error && <Alert componentId="gsb.usage.error" type="warning" closable={false} message={u.error} />}
              {u.totals && (
                <Typography.Text>
                  {u.target}, version {u.version}: {u.totals.queries} queries by {u.totals.users}{' '}
                  {u.totals.users === 1 ? 'user' : 'users'}.
                </Typography.Text>
              )}
              {u.totals && u.totals.queries > 0 && (
                <ul style={{ margin: 0, paddingLeft: 20 }}>
                  {unused.length > 0 && (
                    <li>
                      Nobody read {unused.length === 1 ? 'this field' : 'these fields'}:{' '}
                      {unused.map((f) => f.name).join(', ')}. Consider removing {unused.length === 1 ? 'it' : 'them'} in
                      a new version, after a check with the owners.
                    </li>
                  )}
                  {top.length > 0 && (
                    <li>
                      The most used {top.length === 1 ? 'measure is' : 'measures are'}{' '}
                      {top.map((f) => f.name).join(', ')}. If their queries are slow, try a materialization in the
                      Materialization tab.
                    </li>
                  )}
                </ul>
              )}
              <Table aria-label="Field usage" scrollable>
                <TableRow isHeader>
                  <TableHeader componentId="gsb.usage.h_field" style={{ flex: 2 }}>
                    Field
                  </TableHeader>
                  <TableHeader componentId="gsb.usage.h_kind">Kind</TableHeader>
                  <TableHeader componentId="gsb.usage.h_queries">Queries</TableHeader>
                  <TableHeader componentId="gsb.usage.h_users">Users</TableHeader>
                  <TableHeader componentId="gsb.usage.h_last" style={{ flex: 1.5 }}>
                    Last used
                  </TableHeader>
                </TableRow>
                {u.fields.map((f) => (
                  <TableRow key={`${f.kind}:${f.name}`}>
                    <TableCell multiline style={{ flex: 2 }}>
                      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                        {f.name}
                        {!f.queries && !f.usedBy.length && (
                          <Tag componentId="gsb.usage.unused" color="lemon">
                            Not used
                          </Tag>
                        )}
                        {!f.queries && f.usedBy.length > 0 && (
                          <Typography.Text color="secondary" size="sm">
                            used by {f.usedBy.join(', ')}
                          </Typography.Text>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>{f.kind}</TableCell>
                    <TableCell>{f.queries}</TableCell>
                    <TableCell>{f.users}</TableCell>
                    <TableCell style={{ flex: 1.5 }}>
                      {f.lastUsed ? new Date(f.lastUsed).toLocaleString() : ''}
                    </TableCell>
                  </TableRow>
                ))}
              </Table>
            </>
          )}
        </div>
      )}
    </DataState>
  );
}
