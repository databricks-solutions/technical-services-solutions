import { Alert, Tag, Typography } from '@databricks/design-system';
import type { DictionaryCoverage as Coverage } from '../../../shared/dictionary';
import { useResource } from '../api';

/** How many dictionary metrics and dimensions the chosen tables support. Hidden when the project has no dictionary. */
export function DictionaryCoverage({ projectId, refreshKey }: { projectId: string; refreshKey: string }) {
  const cov = useResource<Coverage>(
    `/api/projects/${projectId}/dictionary/coverage?k=${encodeURIComponent(refreshKey)}`
  );
  const c = cov.data;
  if (!c?.total) return null;
  const all = c.matched.length === c.total;
  return (
    <Alert
      componentId="gsb.sources.dictionary"
      type={all ? 'success' : 'info'}
      closable={false}
      message={`Metric dictionary: these tables support ${c.matched.length} of ${c.total} definitions.`}
      description={
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          {c.matched.length > 0 && (
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', alignItems: 'center' }}>
              <Typography.Text>Supported:</Typography.Text>
              {c.matched.map((m) => (
                <Tag
                  key={`${m.kind}:${m.name}`}
                  componentId="gsb.sources.dictionary_match"
                  color={m.status === 'certified' ? 'teal' : 'default'}
                  title={m.columns.join(', ')}
                >
                  {m.name}
                </Tag>
              ))}
            </div>
          )}
          {c.missing.length > 0 && (
            <Typography.Text color="secondary">
              No matching columns for: {c.missing.map((m) => m.name).join(', ')}. Add the tables they need, or add a
              source column to the dictionary entry.
            </Typography.Text>
          )}
        </div>
      }
    />
  );
}
