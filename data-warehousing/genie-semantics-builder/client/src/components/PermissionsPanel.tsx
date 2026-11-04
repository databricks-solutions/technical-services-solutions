import { Alert, Button, Table, TableCell, TableHeader, TableRow, Tag, Typography } from '@databricks/design-system';
import type { CheckStatus, PermissionCheck } from '../../../shared/readiness';
import { useResource } from '../api';
import { DataState } from './DataState';
import { MONO } from './SqlBlock';

const RESULT: Record<CheckStatus, { color: 'teal' | 'lemon' | 'coral'; label: string }> = {
  pass: { color: 'teal', label: 'Pass' },
  warn: { color: 'lemon', label: 'Not found' },
  fail: { color: 'coral', label: 'Fail' },
};

const GROUPS: { id: PermissionCheck['group']; label: string }[] = [
  { id: 'warehouse', label: 'SQL warehouse' },
  { id: 'sources', label: 'Read the sources' },
  { id: 'sandbox', label: 'Validation sandbox' },
  { id: 'fixes', label: 'Apply metadata fixes' },
];

function Grants({ grants }: { grants: string[] }) {
  if (!grants.length) return null;
  return (
    <pre
      style={{
        ...MONO,
        margin: '4px 0 0',
        padding: 8,
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
        border: '1px solid var(--db-border-base)',
        borderRadius: 4,
      }}
    >
      {grants.join('\n')}
    </pre>
  );
}

/** Live checks of what the user needs, with the GRANT a catalog or table owner can run. */
export function PermissionsPanel({ projectId }: { projectId: string }) {
  const checks = useResource<PermissionCheck[]>(`/api/projects/${projectId}/permissions`);
  const list = checks.data ?? [];
  const missing = list.filter((c) => c.status !== 'pass').flatMap((c) => c.grants);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <Typography.Text color="secondary">
          Checked live with your identity through the Unity Catalog API, with inherited and group grants. A grant through a
          nested group can show as not found. The app never runs
          GRANT statements; send them to the owner.
        </Typography.Text>
        <Button componentId="gsb.permissions.recheck" size="small" onClick={checks.reload}>
          Check again
        </Button>
      </div>
      <DataState status={checks.status} message={checks.error} onRetry={checks.reload}>
        {missing.length > 0 && (
          <Alert
            componentId="gsb.permissions.missing"
            type="warning"
            closable={false}
            message={`${missing.length} grant${missing.length === 1 ? '' : 's'} may be missing`}
            description={<Grants grants={missing} />}
          />
        )}
        <Table>
          <TableRow isHeader>
            <TableHeader componentId="gsb.permissions.col_check">What the app does</TableHeader>
            <TableHeader componentId="gsb.permissions.col_result">Result</TableHeader>
            <TableHeader componentId="gsb.permissions.col_detail">Detail</TableHeader>
          </TableRow>
          {GROUPS.flatMap((g) => {
            const rows = list.filter((c) => c.group === g.id);
            return rows.length
              ? [
                  <TableRow key={g.id}>
                    <TableCell>
                      <Typography.Text bold>{g.label}</Typography.Text>
                    </TableCell>
                    <TableCell>{null}</TableCell>
                    <TableCell>{null}</TableCell>
                  </TableRow>,
                  ...rows.map((c) => (
                    <TableRow key={c.id}>
                      <TableCell>
                        <span style={{ paddingLeft: 16 }}>{c.label}</span>
                      </TableCell>
                      <TableCell>
                        <Tag componentId="gsb.permissions.result" color={RESULT[c.status].color}>
                          {RESULT[c.status].label}
                        </Tag>
                      </TableCell>
                      <TableCell>
                        <div>
                          {c.detail}
                          <Grants grants={c.grants} />
                        </div>
                      </TableCell>
                    </TableRow>
                  )),
                ]
              : [];
          })}
        </Table>
      </DataState>
    </div>
  );
}

/** The one check that matters before a fix runs on a table. */
export function FixPermission({ projectId, table }: { projectId: string; table: string }) {
  const checks = useResource<PermissionCheck[]>(`/api/projects/${projectId}/permissions`);
  const c = checks.data?.find((x) => x.id === `fix:${table}`);
  if (checks.status === 'loading')
    return <Typography.Text color="secondary">Checking your permissions on {table}...</Typography.Text>;
  if (!c || c.status === 'pass') return null;
  return (
    <Alert
      componentId="gsb.permissions.fix"
      type="info"
      closable={false}
      message={c.detail}
      description={<Grants grants={c.grants} />}
    />
  );
}
