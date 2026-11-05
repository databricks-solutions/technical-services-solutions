import { Typography } from '@databricks/design-system';

export const MONO = { fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 12, lineHeight: '18px' };

export function SqlBlock({ label, sql }: { label: string; sql: string }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <Typography.Text bold>{label}</Typography.Text>
      <pre
        style={{
          ...MONO,
          margin: 0,
          padding: 12,
          maxHeight: 320,
          overflow: 'auto',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          border: '1px solid var(--db-border-base)',
          borderRadius: 4,
        }}
      >
        {sql}
      </pre>
    </div>
  );
}
