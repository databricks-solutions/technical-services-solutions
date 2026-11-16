import type { ReactNode } from 'react';
import { Typography } from '@databricks/design-system';

/**
 * The header of every page: the title with optional tags on the left, the page actions on the right, and the
 * description under them. One pattern, so the title sits in the same place on each page.
 */
export function PageHeader({
  title,
  tags,
  description,
  actions,
}: {
  title: ReactNode;
  tags?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: 16,
          flexWrap: 'wrap',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', minWidth: 0 }}>
          <Typography.Title level={2} withoutMargins id="gsb-page-title">
            {title}
          </Typography.Title>
          {tags}
        </div>
        {actions && <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>{actions}</div>}
      </div>
      {description && (
        <Typography.Paragraph withoutMargins color="secondary" style={{ maxWidth: 820 }}>
          {description}
        </Typography.Paragraph>
      )}
    </header>
  );
}
