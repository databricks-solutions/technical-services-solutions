import { useState } from 'react';
import {
  Button,
  Empty,
  Input,
  SearchIcon,
  Table,
  TableCell,
  TableHeader,
  TableRow,
  Tag,
  Typography,
} from '@databricks/design-system';
import type { AdoptableView } from '../../../shared/promote';
import type { useResource } from '../api';
import { DataState } from './DataState';
import { ImportModal } from './ImportModal';
import { OpenInCatalog } from './OpenInCatalog';

/** Metric views in Unity Catalog that the app does not manage yet. Adopt brings one into a project. */
export function AdoptPanel({ data }: { data: ReturnType<typeof useResource<AdoptableView[]>> }) {
  const [q, setQ] = useState('');
  const [adopting, setAdopting] = useState<string>();
  const views = (data.data ?? []).filter((v) =>
    `${v.fullName} ${v.comment ?? ''} ${v.owner ?? ''}`.toLowerCase().includes(q.trim().toLowerCase())
  );
  return (
    <DataState status={data.status} message={data.error} onRetry={data.reload}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Typography.Text color="secondary">
          Metric views in Unity Catalog that you can see and that the app does not manage yet. Adopt one to bring it
          into a project as version 1. Then check its sources, optimize it, and publish new versions from the app. The
          view in Unity Catalog does not change until you publish.
        </Typography.Text>
        {(data.data?.length ?? 0) > 0 ? (
          <>
            <div style={{ maxWidth: 420 }}>
              <Input
                componentId="gsb.adopt.search"
                prefix={<SearchIcon />}
                placeholder="Filter by name, description or owner"
                aria-label="Filter the metric views to adopt"
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
            </div>
            <Table aria-label="Metric views to adopt" scrollable>
              <TableRow isHeader>
                <TableHeader componentId="gsb.adopt.h_view" style={{ flex: 3 }}>
                  Metric view
                </TableHeader>
                <TableHeader componentId="gsb.adopt.h_comment" style={{ flex: 3 }}>
                  Description
                </TableHeader>
                <TableHeader componentId="gsb.adopt.h_owner" style={{ flex: 2 }}>
                  Owner
                </TableHeader>
                <TableHeader componentId="gsb.adopt.h_changed" style={{ flex: 1 }}>
                  Last changed
                </TableHeader>
                <TableHeader componentId="gsb.adopt.h_actions" style={{ flex: 2 }}>
                  Actions
                </TableHeader>
              </TableRow>
              {views.map((v) => (
                <TableRow key={v.fullName}>
                  <TableCell style={{ flex: 3 }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                      <code style={{ overflowWrap: 'anywhere' }}>{v.fullName}</code>
                      {v.managedByOther && (
                        <Tag componentId="gsb.adopt.other" color="lemon">
                          Managed by another user in the app
                        </Tag>
                      )}
                    </div>
                  </TableCell>
                  <TableCell multiline style={{ flex: 3 }}>
                    <Typography.Text color={v.comment ? undefined : 'secondary'}>
                      {v.comment || 'No description'}
                    </Typography.Text>
                  </TableCell>
                  <TableCell style={{ flex: 2 }}>{v.owner ?? ''}</TableCell>
                  <TableCell style={{ flex: 1 }}>
                    {v.lastAltered ? new Date(v.lastAltered).toLocaleDateString() : ''}
                  </TableCell>
                  <TableCell style={{ flex: 2 }}>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                      <Button
                        componentId="gsb.adopt.adopt"
                        type="primary"
                        size="small"
                        aria-label={`Adopt ${v.fullName}`}
                        onClick={() => setAdopting(v.fullName)}
                      >
                        Adopt
                      </Button>
                      <OpenInCatalog fullName={v.fullName} />
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </Table>
            {!views.length && <Typography.Text color="secondary">No metric view matches the filter.</Typography.Text>}
          </>
        ) : (
          <Empty
            title="Nothing to adopt"
            description="The app manages every metric view that you can see, or there are none yet. Metric views made outside the app show here."
          />
        )}
      </div>
      {adopting && <ImportModal initialView={adopting} onClose={() => setAdopting(undefined)} />}
    </DataState>
  );
}
