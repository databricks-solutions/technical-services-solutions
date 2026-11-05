import { NewWindowIcon, Typography } from '@databricks/design-system';
import { useResource } from '../api';

/** Opens a table or view in Catalog Explorer. Hidden until the workspace URL is known. */
export function OpenInCatalog({ fullName, label = 'Open in Unity Catalog' }: { fullName: string; label?: string }) {
  const base = useResource<{ workspaceUrl: string | null }>('/api/config').data?.workspaceUrl;
  const parts = fullName.split('.');
  if (!base || parts.length !== 3) return null;
  const href = `${base}/explore/data/${parts.map(encodeURIComponent).join('/')}`;
  return (
    <Typography.Link
      componentId="gsb.uc.open"
      href={href}
      openInNewTab
      aria-label={`${label}: ${fullName}`}
      style={{ display: 'inline-flex', alignItems: 'center', gap: 4, whiteSpace: 'nowrap' }}
    >
      {label} <NewWindowIcon />
    </Typography.Link>
  );
}
