import type { ReactNode } from 'react';
import { CheckCircleFillIcon, Typography } from '@databricks/design-system';

/** A good result that stays on the page: one line with a green check, and optional detail under it. */
export function StatusLine({ message, children }: { message: ReactNode; children?: ReactNode }) {
  return (
    <div role="status" style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
      <CheckCircleFillIcon style={{ color: 'var(--db-alert-icon-color-success)', marginTop: 3 }} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}>
        <Typography.Text>{message}</Typography.Text>
        {children}
      </div>
    </div>
  );
}
