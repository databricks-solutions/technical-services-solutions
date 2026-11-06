import { useState } from 'react';
import { useNavigate } from 'react-router';
import { Button, Empty, Table, TableCell, TableHeader, TableRow, Tag, Typography } from '@databricks/design-system';
import type { LibraryRow } from '../../../shared/promote';
import { useResource } from '../api';
import { DataState } from '../components/DataState';
import { DiscoverPanel } from '../components/DiscoverPanel';
import { ImportModal } from '../components/ImportModal';
import { OpenInCatalog } from '../components/OpenInCatalog';
import { subPath } from './ProjectsPage';

function Health({ r }: { r: LibraryRow }) {
  if (!r.health) return <Typography.Text color="secondary">Not checked</Typography.Text>;
  const tag = { ok: ['teal', 'OK'], warning: ['lemon', 'Warning'], error: ['coral', 'Error'] } as const;
  const [color, label] = tag[r.health.status];
  return (
    <Tag componentId="gsb.library.health" color={color} title={`Checked ${new Date(r.health.at).toLocaleString()}`}>
      {label}, {new Date(r.health.at).toLocaleDateString()}
    </Tag>
  );
}

function Behind({ r }: { r: LibraryRow }) {
  if (!r.promoted) return <Tag componentId="gsb.library.state">Not promoted</Tag>;
  const n = r.latest.version - r.promoted.version;
  return n > 0 ? (
    <Tag componentId="gsb.library.state" color="lemon">
      {n} version{n === 1 ? '' : 's'} newer than UC
    </Tag>
  ) : (
    <Tag componentId="gsb.library.state" color="teal">
      Up to date
    </Tag>
  );
}

/** Every metric view the user designs, where it lives in Unity Catalog, and how far the latest version is ahead. */
export function LibraryPage() {
  const navigate = useNavigate();
  const data = useResource<LibraryRow[]>('/api/library');
  const [importing, setImporting] = useState(false);
  const [discovering, setDiscovering] = useState(false);
  const rows = data.data ?? [];
  const sandbox = rows.filter((r) => r.sandboxView);
  return (
    <DataState status={data.status} message={data.error} onRetry={data.reload}>
      <div style={{ marginBottom: 16, display: 'flex', gap: 8 }}>
        <Button componentId="gsb.library.import" type="primary" onClick={() => setImporting(true)}>
          Import a metric view
        </Button>
        <Button componentId="gsb.library.discover" onClick={() => setDiscovering((d) => !d)}>
          {discovering ? 'Close discover' : 'Discover and consolidate KPIs'}
        </Button>
      </div>
      {discovering && (
        <div style={{ marginBottom: 24 }}>
          <DiscoverPanel />
        </div>
      )}
      {importing && <ImportModal onClose={() => setImporting(false)} />}
      {rows.length === 0 ? (
        <Empty
          title="No metric views yet"
          description="Design a metric view in a sub-project, or import one made outside the app. It shows here."
        />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Table aria-label="Metric views" scrollable>
            <TableRow isHeader>
              <TableHeader componentId="gsb.library.h_view">Metric view</TableHeader>
              <TableHeader componentId="gsb.library.h_project">Project</TableHeader>
              <TableHeader componentId="gsb.library.h_promoted">In Unity Catalog</TableHeader>
              <TableHeader componentId="gsb.library.h_latest">Latest version</TableHeader>
              <TableHeader componentId="gsb.library.h_state">State</TableHeader>
              <TableHeader componentId="gsb.library.h_health">Health</TableHeader>
              <TableHeader componentId="gsb.library.h_actions">Actions</TableHeader>
            </TableRow>
            {rows.map((r) => (
              <TableRow key={r.projectId}>
                <TableCell>
                  {r.target ? (
                    <code>{r.target}</code>
                  ) : (
                    <Typography.Text color="secondary">{r.name} (no target)</Typography.Text>
                  )}
                </TableCell>
                <TableCell>
                  {r.project} / {r.subProject}
                </TableCell>
                <TableCell>
                  {r.promoted
                    ? `Version ${r.promoted.version}, ${r.promoted.by}, ${new Date(r.promoted.at).toLocaleDateString()}`
                    : 'Not promoted'}
                </TableCell>
                <TableCell>
                  {r.latest.version} ({r.latest.status === 'validated' ? 'validated' : 'not validated'})
                </TableCell>
                <TableCell>
                  <Behind r={r} />
                </TableCell>
                <TableCell>
                  <Health r={r} />
                </TableCell>
                <TableCell>
                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    {r.target && r.promoted && <OpenInCatalog fullName={r.target} />}
                    {r.promoted && (
                      <Button
                        componentId="gsb.library.health_open"
                        size="small"
                        onClick={() => void navigate(`${subPath(r.parentId, r.projectId, 'designer')}?tab=promote`)}
                      >
                        Health and drift
                      </Button>
                    )}
                    <Button
                      componentId="gsb.library.open"
                      size="small"
                      onClick={() => void navigate(subPath(r.parentId, r.projectId, 'designer'))}
                    >
                      Open in designer
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </Table>
          {sandbox.length > 0 && (
            <>
              <Typography.Title level={4} withoutMargins>
                Sandbox views
              </Typography.Title>
              <Typography.Text color="secondary">
                Created for validation, stress tests and Genie checks. They are not the real views, and a project delete
                drops them.
              </Typography.Text>
              <Table aria-label="Sandbox views" scrollable>
                <TableRow isHeader>
                  <TableHeader componentId="gsb.library.h_sandbox">Sandbox view</TableHeader>
                  <TableHeader componentId="gsb.library.h_sandbox_project">Project</TableHeader>
                  <TableHeader componentId="gsb.library.h_sandbox_open"> </TableHeader>
                </TableRow>
                {sandbox.map((r) => (
                  <TableRow key={r.projectId}>
                    <TableCell>
                      <code>{r.sandboxView}</code>
                    </TableCell>
                    <TableCell>
                      {r.project} / {r.subProject}
                    </TableCell>
                    <TableCell>{r.sandboxView && <OpenInCatalog fullName={r.sandboxView} />}</TableCell>
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
