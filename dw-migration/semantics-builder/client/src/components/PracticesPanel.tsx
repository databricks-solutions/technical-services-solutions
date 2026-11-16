import { useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { Alert, Button, Checkbox, Tag, Typography } from '@databricks/design-system';
import type { PracticeCheck, PracticeSeverity } from '../../../shared/optimize';
import { api } from '../api';

const SEVERITY: Record<PracticeSeverity, { color: 'coral' | 'lemon' | 'default'; label: string }> = {
  fix: { color: 'coral', label: 'Fix' },
  improve: { color: 'lemon', label: 'Improve' },
  info: { color: 'default', label: 'Note' },
};

/** Rule-based best practices. Fixes go to the AI as one instruction and become a new design version. */
export function PracticesPanel({ checks }: { checks: PracticeCheck[] }) {
  const { projectId = '', parentId = '' } = useParams();
  const navigate = useNavigate();
  // Notes are advice, so they never count against the view.
  const rules = checks.filter((c) => c.severity !== 'info');
  const failed = rules.filter((c) => c.fields.length);
  const fixable = failed.filter((c) => c.instruction);
  const [off, setOff] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const chosen = fixable.filter((c) => !off.includes(c.id));
  const blocking = failed.filter((c) => c.severity === 'fix').length;

  const fix = () => {
    setBusy(true);
    setError(undefined);
    const instruction = chosen
      .map((c) => c.instruction)
      .join(' ')
      .slice(0, 2000);
    api(`/api/projects/${projectId}/designs/refine`, { instruction }).then(
      () => void navigate(`/projects/${parentId}/sub/${projectId}/designer`),
      (err: unknown) => {
        setBusy(false);
        setError((err as Error).message);
      }
    );
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Typography.Title level={4} withoutMargins>
        Best practices
      </Typography.Title>
      <Alert
        componentId="gsb.practices.summary"
        type={blocking ? 'warning' : failed.length ? 'info' : 'success'}
        closable={false}
        message={
          blocking
            ? `${blocking} rule${blocking === 1 ? '' : 's'} to fix before the view is ready to certify.`
            : failed.length
              ? 'Ready to certify. Some improvements are still open.'
              : 'Every rule passes. The view is ready to certify.'
        }
        description={`${rules.length - failed.length} of ${rules.length} rules pass. Rule-based, from the YAML; no model call.`}
      />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {checks.map((c) => {
          const pass = !c.fields.length;
          return (
            <div
              key={c.id}
              style={{
                display: 'flex',
                gap: 12,
                alignItems: 'flex-start',
                padding: 12,
                border: '1px solid var(--db-border-base)',
                borderRadius: 8,
              }}
            >
              {c.instruction ? (
                <Checkbox
                  componentId="gsb.practices.pick"
                  aria-label={`Fix: ${c.title}`}
                  isChecked={!off.includes(c.id)}
                  onChange={(on) => setOff(on ? off.filter((x) => x !== c.id) : [...off, c.id])}
                />
              ) : (
                <span style={{ width: 16 }} />
              )}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  <Typography.Text bold>{c.title}</Typography.Text>
                  {pass ? (
                    <Tag componentId="gsb.practices.result" color="teal">
                      Pass
                    </Tag>
                  ) : (
                    <Tag componentId="gsb.practices.result" color={SEVERITY[c.severity].color}>
                      {SEVERITY[c.severity].label}
                    </Tag>
                  )}
                </div>
                <Typography.Text color="secondary">{c.why}</Typography.Text>
                {!pass && (
                  <Typography.Text>
                    {c.fields.length} field{c.fields.length === 1 ? '' : 's'}: {c.fields.join(', ')}
                  </Typography.Text>
                )}
              </div>
            </div>
          );
        })}
      </div>
      {fixable.length > 0 && (
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <Button componentId="gsb.practices.fix" type="primary" loading={busy} disabled={!chosen.length} onClick={fix}>
            Fix {chosen.length} with AI
          </Button>
          <Typography.Text color="secondary">
            Creates a new design version in Metric Designer. Review it and validate it again before you stress test.
          </Typography.Text>
        </div>
      )}
      {error && <Alert componentId="gsb.practices.error" type="error" closable={false} message={error} />}
    </div>
  );
}
