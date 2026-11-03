import { useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import {
  Alert,
  Button,
  Modal,
  Table,
  TableCell,
  TableHeader,
  TableRow,
  Tag,
  Typography,
} from '@databricks/design-system';
import type { CheckStatus, ReadinessView, Recommendation, SourceReadiness } from '../../../shared/readiness';
import { api, useResource } from '../api';
import { DataState } from '../components/DataState';

type TagColor = 'teal' | 'lemon' | 'coral' | 'default';

const CHECK_TAG: Record<CheckStatus, { color: TagColor; label: string }> = {
  pass: { color: 'teal', label: 'Pass' },
  warn: { color: 'lemon', label: 'Warning' },
  fail: { color: 'coral', label: 'Fail' },
};

const STATUS_TAG: Record<Recommendation['status'], { color: TagColor; label: string }> = {
  proposed: { color: 'default', label: 'Proposed' },
  approved: { color: 'lemon', label: 'Running' },
  applied: { color: 'teal', label: 'Applied' },
  rejected: { color: 'default', label: 'Rejected' },
  failed: { color: 'coral', label: 'Failed' },
};

function ScoreTag({ score }: { score: number | null }) {
  if (score === null) return <Tag componentId="gsb.sources.score">Not scored</Tag>;
  const [color, label]: [TagColor, string] =
    score >= 80 ? ['teal', 'Ready'] : score >= 50 ? ['lemon', 'Needs work'] : ['coral', 'Not ready'];
  return (
    <Tag componentId="gsb.sources.score" color={color}>
      {score} - {label}
    </Tag>
  );
}

function Sql({ statements }: { statements: string[] }) {
  return (
    <pre
      style={{
        margin: 0,
        padding: 12,
        maxHeight: 320,
        overflow: 'auto',
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
        fontSize: 12,
        border: '1px solid var(--db-border-base)',
        borderRadius: 4,
      }}
    >
      {statements.map((s) => `${s};`).join('\n')}
    </pre>
  );
}

function SourceDetail({ source }: { source: SourceReadiness }) {
  const report = source.report;
  if (!report) return null;
  return (
    <section aria-label={source.fullName} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <Typography.Title level={4} withoutMargins>
          {source.fullName}
        </Typography.Title>
        <ScoreTag score={report.score} />
      </div>
      {report.assessment && (
        <Alert
          componentId="gsb.sources.ai_notice"
          type="info"
          closable={false}
          message="Assessed by AI. Check the findings against your knowledge of the data."
          description={
            <>
              <Typography.Paragraph>{report.assessment.summary}</Typography.Paragraph>
              {report.assessment.findings.length > 0 && (
                <ul style={{ margin: 0, paddingLeft: 20 }}>
                  {report.assessment.findings.map((f) => (
                    <li key={f}>{f}</li>
                  ))}
                </ul>
              )}
            </>
          }
        />
      )}
      <Table>
        <TableRow isHeader>
          <TableHeader componentId="gsb.sources.check_col_check">Check</TableHeader>
          <TableHeader componentId="gsb.sources.check_col_result">Result</TableHeader>
          <TableHeader componentId="gsb.sources.check_col_detail">Detail</TableHeader>
        </TableRow>
        {report.checks.map((c) => (
          <TableRow key={c.id}>
            <TableCell>{c.label}</TableCell>
            <TableCell>
              <Tag componentId="gsb.sources.check_status" color={CHECK_TAG[c.status].color}>
                {CHECK_TAG[c.status].label}
              </Tag>
            </TableCell>
            <TableCell>{c.detail}</TableCell>
          </TableRow>
        ))}
      </Table>
    </section>
  );
}

function FixCard({
  fix,
  busy,
  onApply,
  onReject,
}: {
  fix: Recommendation;
  busy: boolean;
  onApply: () => void;
  onReject: () => void;
}) {
  const open = fix.status === 'proposed' || fix.status === 'failed';
  return (
    <article
      aria-label={fix.title}
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        padding: 16,
        border: '1px solid var(--db-border-base)',
        borderRadius: 8,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <Typography.Text bold>{fix.title}</Typography.Text>
        <Tag componentId="gsb.sources.fix_status" color={STATUS_TAG[fix.status].color}>
          {STATUS_TAG[fix.status].label}
        </Tag>
      </div>
      <Typography.Text color="secondary">{fix.rationale}</Typography.Text>
      <Sql statements={fix.statements} />
      {fix.error && <Alert componentId="gsb.sources.fix_error" type="error" closable={false} message={fix.error} />}
      {fix.decidedBy && !open && (
        <Typography.Text color="secondary" size="sm">
          {STATUS_TAG[fix.status].label} by {fix.decidedBy}
          {fix.decidedAt ? ` on ${new Date(fix.decidedAt).toLocaleString()}` : ''}
        </Typography.Text>
      )}
      {open && (
        <div style={{ display: 'flex', gap: 8 }}>
          <Button componentId="gsb.sources.fix_review" type="primary" disabled={busy} onClick={onApply}>
            {fix.status === 'failed' ? 'Review and retry' : 'Review and apply'}
          </Button>
          <Button componentId="gsb.sources.fix_reject" disabled={busy} onClick={onReject}>
            Reject
          </Button>
        </div>
      )}
    </article>
  );
}

export function SourcesPage() {
  const { projectId = '' } = useParams();
  const navigate = useNavigate();
  const view = useResource<ReadinessView>(`/api/projects/${projectId}/readiness`);
  const [busy, setBusy] = useState<string>();
  const [error, setError] = useState<string>();
  const [reviewing, setReviewing] = useState<Recommendation>();

  const post = (key: string, path: string, body: unknown = {}) => {
    setBusy(key);
    setError(undefined);
    return api<ReadinessView>(path, body).then(
      (v) => {
        setBusy(undefined);
        view.setData(v);
      },
      (err: unknown) => {
        setBusy(undefined);
        setError((err as Error).message);
      }
    );
  };

  const data = view.data;
  const status = view.status === 'ready' && data && !data.sources.length ? 'empty' : view.status;
  const assessed = data?.sources.some((s) => s.report) ?? false;

  return (
    <DataState
      status={status}
      message={status === 'empty' ? 'Confirm a Semantic Brief to register its candidate sources.' : view.error}
      onRetry={view.reload}
      emptyAction={
        <Button componentId="gsb.sources.go_intake" onClick={() => void navigate(`/projects/${projectId}/intake`)}>
          Go to Intent & Context
        </Button>
      }
    >
      {data && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'flex-start' }}>
            <Typography.Text color="secondary">
              The assessment reads table metadata with your permissions. Nothing changes in Unity Catalog until you
              approve a fix.
            </Typography.Text>
            <Button
              componentId="gsb.sources.run"
              type="primary"
              loading={busy === 'run'}
              disabled={!!busy}
              onClick={() => void post('run', `/api/projects/${projectId}/readiness/run`)}
            >
              {assessed ? 'Assess again' : 'Assess sources'}
            </Button>
            {busy === 'run' && (
              <div role="status">
                <Typography.Text color="secondary">
                  Checking {data.sources.length} tables. This can take a minute.
                </Typography.Text>
              </div>
            )}
            {error && <Alert componentId="gsb.sources.error" type="error" closable={false} message={error} />}
          </div>

          <Table>
            <TableRow isHeader>
              <TableHeader componentId="gsb.sources.col_table">Table</TableHeader>
              <TableHeader componentId="gsb.sources.col_role">Role</TableHeader>
              <TableHeader componentId="gsb.sources.col_score">Readiness</TableHeader>
              <TableHeader componentId="gsb.sources.col_checks">Checks</TableHeader>
            </TableRow>
            {data.sources.map((s) => {
              const checks = s.report?.checks ?? [];
              const count = (st: CheckStatus) => checks.filter((c) => c.status === st).length;
              return (
                <TableRow key={s.sourceId}>
                  <TableCell>{s.fullName}</TableCell>
                  <TableCell>
                    {s.role === 'unknown' ? 'Not known yet' : s.role === 'fact' ? 'Fact' : 'Dimension'}
                  </TableCell>
                  <TableCell>{s.report ? <ScoreTag score={s.report.score} /> : 'Not assessed'}</TableCell>
                  <TableCell>
                    {s.report ? `${count('pass')} pass, ${count('warn')} warning, ${count('fail')} fail` : '-'}
                  </TableCell>
                </TableRow>
              );
            })}
          </Table>

          {data.recommendations.length > 0 && (
            <section aria-labelledby="gsb-fixes" style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <Typography.Title level={3} id="gsb-fixes" withoutMargins>
                Proposed fixes
              </Typography.Title>
              <Typography.Text color="secondary">
                Apply primary keys before the foreign keys that reference them.
              </Typography.Text>
              {data.recommendations.map((r) => (
                <FixCard
                  key={r.id}
                  fix={r}
                  busy={!!busy}
                  onApply={() => setReviewing(r)}
                  onReject={() => void post(r.id, `/api/projects/${projectId}/recommendations/${r.id}/reject`)}
                />
              ))}
            </section>
          )}

          {data.sources.map((s) => (
            <SourceDetail key={s.sourceId} source={s} />
          ))}

          <Modal
            componentId="gsb.sources.apply_modal"
            title={reviewing ? `Apply: ${reviewing.title}` : ''}
            visible={!!reviewing}
            okText="Run SQL"
            cancelText="Cancel"
            okButtonProps={{ loading: !!reviewing && busy === reviewing.id }}
            onCancel={() => setReviewing(undefined)}
            onOk={() => {
              if (!reviewing) return;
              void post(reviewing.id, `/api/projects/${projectId}/recommendations/${reviewing.id}/apply`, {
                statements: reviewing.statements,
              }).then(() => setReviewing(undefined));
            }}
          >
            {reviewing && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                <Alert
                  componentId="gsb.sources.apply_warning"
                  type="warning"
                  closable={false}
                  message="This SQL runs as you on the SQL warehouse and changes Unity Catalog metadata. It does not change table data."
                />
                <Sql statements={reviewing.statements} />
              </div>
            )}
          </Modal>
        </div>
      )}
    </DataState>
  );
}
