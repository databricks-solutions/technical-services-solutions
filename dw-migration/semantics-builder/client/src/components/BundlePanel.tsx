import { useState } from 'react';
import { Button, DownloadIcon, SimpleSelect, SimpleSelectOption, Typography } from '@databricks/design-system';
import type { BundleView } from '../../../shared/bundle';
import { useResource } from '../api';
import { DataState } from './DataState';
import { SqlBlock } from './SqlBlock';

/**
 * The promoted view as a Declarative Automation Bundle for the customer's Git and CI/CD: a deploy job and a nightly
 * check job, both SQL files on a warehouse. The app only builds the files; the user deploys them, as themselves.
 */
export function BundlePanel({ projectId }: { projectId: string }) {
  const res = useResource<BundleView>(`/api/projects/${projectId}/bundle`);
  const b = res.data?.bundle;
  const [shown, setShown] = useState('databricks.yml');

  const download = () => {
    if (!b) return;
    const bytes = Uint8Array.from(atob(b.zip), (c) => c.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], { type: 'application/zip' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = b.fileName;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <DataState status={res.status} message={res.error} onRetry={res.reload}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <Typography.Text color="secondary">
          Keep the promoted view in Git and deploy it from your own pipeline. The bundle has a deploy job (create the
          view, then run its tests) and a nightly check (the view is still a metric view with the same fields, and the
          tests pass). Every task is a SQL file on a SQL warehouse. A failing check fails the job and emails the owner.
        </Typography.Text>
        {!b ? (
          <Typography.Text>Promote a version first.</Typography.Text>
        ) : (
          <>
            <Typography.Text>
              {b.target}, version {b.version}. {Object.keys(b.files).length} files.
            </Typography.Text>
            <div>
              <Button componentId="gsb.bundle.download" type="primary" icon={<DownloadIcon />} onClick={download}>
                Download {b.fileName}
              </Button>
            </div>
            <div style={{ maxWidth: 360 }}>
              <SimpleSelect
                componentId="gsb.bundle.file"
                id="bundle-file"
                aria-label="File"
                value={shown}
                onChange={(e) => setShown(e.target.value)}
              >
                {Object.keys(b.files).map((f) => (
                  <SimpleSelectOption key={f} value={f}>
                    {f}
                  </SimpleSelectOption>
                ))}
              </SimpleSelect>
            </div>
            <SqlBlock label={shown} sql={b.files[shown] ?? ''} />
          </>
        )}
      </div>
    </DataState>
  );
}
