import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import {
  Button,
  Empty,
  Table,
  TableCell,
  TableHeader,
  TableRow,
  Tabs,
  Tag,
  Typography,
} from '@databricks/design-system';
import type { AdoptableView, LibraryRow } from '../../../shared/promote';
import { AdoptPanel } from '../components/AdoptPanel';
import { useTab } from '../useTab';
import { DRIFT_CHECKED, useResource } from '../api';
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
  const { reload } = data;
  useEffect(() => {
    window.addEventListener(DRIFT_CHECKED, reload);
    return () => window.removeEventListener(DRIFT_CHECKED, reload);
  }, [reload]);
  const [importing, setImporting] = useState(false);
  const adoptable = useResource<AdoptableView[]>('/api/library/adoptable');
  // A user with no managed views starts on Adopt.
  const [tab, setTab] = useTab(
    ['optimized', 'adopt'] as const,
    data.status === 'ready' && !data.data?.length ? 'adopt' : 'optimized'
  );
  const [discovering, setDiscovering] = useState(false);
  const rows = data.data ?? [];
  const sandbox = rows.filter((r) => r.sandboxView);
  return (
    <DataState status={data.status} message={data.error} onRetry={data.reload}>
      <div style={{ marginBottom: 16, display: 'flex', gap: 8 }}>
        <Button componentId="gsb.library.import" onClick={() => setImporting(true)}>
          Adopt by name
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
      <Tabs.Root componentId="gsb.library.tabs" value={tab} onValueChange={setTab}>
        <Tabs.List>
          <Tabs.Trigger value="optimized">Optimized semantics ({rows.length})</Tabs.Trigger>
          <Tabs.Trigger value="adopt">
            Adopt{adoptable.status === 'ready' ? ` (${adoptable.data?.length ?? 0})` : ''}
          </Tabs.Trigger>
        </Tabs.List>
        <Tabs.Content value="adopt">
          <div style={{ paddingTop: 16 }}>
            <AdoptPanel data={adoptable} />
          </div>
        </Tabs.Content>
        <Tabs.Content value="optimized">
          <div style={{ paddingTop: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
            <Typography.Text color="secondary">
              Metric views that the app manages for you: designed here or adopted, with versions, validation, tests,
              publishing to Unity Catalog, and health checks.
            </Typography.Text>
            {rows.length === 0 ? (
              <Empty
                title="No optimized metric views yet"
                description="Design a metric view in a sub-project, or adopt one from the Adopt tab. It shows here."
                button={
                  <Button componentId="gsb.library.to_adopt" onClick={() => setTab('adopt')}>
                    See metric views to adopt
                  </Button>
                }
              />
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                {/* A narrow page scrolls the table sideways instead of cutting the names. */}
                <div style={{ overflowX: 'auto' }}>
                  <Table aria-label="Metric views" scrollable style={{ minWidth: 1100 }}>
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
                        <TableCell multiline>
                          {r.target ? (
                            <code>{r.target}</code>
                          ) : (
                            <Typography.Text color="secondary">{r.name} (no target)</Typography.Text>
                          )}
                        </TableCell>
                        <TableCell multiline>
                          {r.project} / {r.subProject}
                        </TableCell>
                        <TableCell multiline>
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
                                onClick={() => void navigate(subPath(r.parentId, r.projectId, 'publish'))}
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
                </div>
                {sandbox.length > 0 && (
                  <>
                    <Typography.Title level={4} withoutMargins>
                      Sandbox views
                    </Typography.Title>
                    <Typography.Text color="secondary">
                      Created for validation, stress tests and Genie checks. They are not the real views, and a project
                      delete drops them.
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
          </div>
        </Tabs.Content>
      </Tabs.Root>
    </DataState>
  );
}
