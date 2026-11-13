import { useState } from 'react';
import {
  Alert,
  Button,
  FormUI,
  Input,
  Modal,
  Table,
  TableCell,
  TableHeader,
  TableRow,
  Tag,
  Typography,
} from '@databricks/design-system';
import type { CertificationView, DataChecks } from '../../../shared/certify';
import type { CheckStatus, ReadinessCheck } from '../../../shared/readiness';
import { api, useResource } from '../api';
import { REVIEW_TAG } from './ApprovalPanel';
import { DataState } from './DataState';
import { SqlBlock } from './SqlBlock';

const CHECK: Record<CheckStatus, { color: 'teal' | 'lemon' | 'coral'; label: string }> = {
  pass: { color: 'teal', label: 'Pass' },
  warn: { color: 'lemon', label: 'Warning' },
  fail: { color: 'coral', label: 'Fail' },
};

/** A short result of the data checks: the worst status and the count of issues. */
export function ChecksTag({ data }: { data: DataChecks | null }) {
  if (!data) return <Tag componentId="gsb.certify.not_checked">Not checked</Tag>;
  const fails = data.checks.filter((c) => c.status === 'fail').length;
  const warns = data.checks.filter((c) => c.status === 'warn').length;
  const worst: CheckStatus = fails ? 'fail' : warns ? 'warn' : 'pass';
  return (
    <Tag componentId="gsb.certify.checks" color={CHECK[worst].color}>
      {fails || warns ? `${fails} failed, ${warns} warnings` : 'All passed'}
    </Tag>
  );
}

export function ChecksTable({ label, checks }: { label: string; checks: ReadinessCheck[] }) {
  return (
    <Table aria-label={label}>
      <TableRow isHeader>
        <TableHeader componentId="gsb.certify.h_check">Check</TableHeader>
        <TableHeader componentId="gsb.certify.h_result">Result</TableHeader>
        <TableHeader componentId="gsb.certify.h_detail">Detail</TableHeader>
      </TableRow>
      {checks.map((c) => (
        <TableRow key={c.id}>
          <TableCell>{c.label}</TableCell>
          <TableCell>
            <Tag componentId="gsb.certify.check" color={CHECK[c.status].color}>
              {CHECK[c.status].label}
            </Tag>
          </TableCell>
          <TableCell>{c.detail}</TableCell>
        </TableRow>
      ))}
    </Table>
  );
}

const STATUS_TAG = (status: string | null) =>
  status === 'certified' ? (
    <Tag componentId="gsb.certify.status" color="teal">
      Certified
    </Tag>
  ) : status ? (
    <Tag componentId="gsb.certify.status" color="coral">
      {status === 'deprecated' ? 'Deprecated' : status}
    </Tag>
  ) : (
    <Tag componentId="gsb.certify.status">Not certified</Tag>
  );

/**
 * Certify the data of the sub-project: run the data checks, ask a named reviewer, then set the governed tag
 * with SQL that you examine first. The app keeps the check results only, never the data.
 */
export function CertifyPanel({ projectId }: { projectId: string }) {
  const res = useResource<CertificationView>(`/api/projects/${projectId}/certification`);
  const [reviewer, setReviewer] = useState('');
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState<string>();
  const [error, setError] = useState<string>();
  const [examining, setExamining] = useState(false);
  const v = res.data;
  const r = v?.review;
  const checked = !!v?.tables.length && v.tables.every((t) => t.data);
  const allCertified = !!v?.tables.length && v.tables.every((t) => t.status === 'certified');

  const post = (key: string, path: string, body: unknown, after?: () => void) => {
    setBusy(key);
    setError(undefined);
    api<CertificationView>(`/api/projects/${projectId}/${path}`, body).then(
      (next) => {
        setBusy(undefined);
        res.setData(next);
        after?.();
      },
      (err: unknown) => {
        setBusy(undefined);
        setError((err as Error).message);
      }
    );
  };

  return (
    <DataState status={res.status} message={res.error} onRetry={res.reload}>
      {v && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, paddingTop: 16 }}>
          <Typography.Text color="secondary">
            Certify the tables before you build on them. The data checks read each table once, as you: the row count,
            the last data change, and the nulls, empty strings and constant columns of each column. The app keeps the
            check results only, never the data. Then a named reviewer approves the tables, and you set the Unity Catalog
            tag {"'system.certification_status' = 'certified'"} on each table.
          </Typography.Text>
          {v.statusError && (
            <Alert componentId="gsb.certify.status_error" type="warning" closable={false} message={v.statusError} />
          )}
          <div>
            <Button
              componentId="gsb.certify.run"
              loading={busy === 'run'}
              disabled={!!busy || !v.tables.length}
              onClick={() => post('run', 'data-checks', {})}
            >
              {checked ? 'Run the data checks again' : 'Run the data checks'}
            </Button>
          </div>
          {busy === 'run' && (
            <div role="status">
              <Typography.Text color="secondary">
                Checking {v.tables.length} tables. A full scan of a large table can take some minutes.
              </Typography.Text>
            </div>
          )}

          {v.tables.map((t) => (
            <section
              key={t.sourceId}
              aria-label={t.fullName}
              style={{ display: 'flex', flexDirection: 'column', gap: 8 }}
            >
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <Typography.Text bold>{t.fullName}</Typography.Text>
                {STATUS_TAG(t.status)}
                <ChecksTag data={t.data} />
                {t.data && (
                  <Typography.Text color="secondary" size="sm">
                    Checked by {t.data.checkedBy} on {new Date(t.data.checkedAt).toLocaleString()}
                  </Typography.Text>
                )}
              </div>
              {t.data && <ChecksTable label={`Data checks of ${t.fullName}`} checks={t.data.checks} />}
            </section>
          ))}

          <section
            style={{
              border: '1px solid var(--db-border-base)',
              borderRadius: 8,
              padding: 12,
              display: 'flex',
              flexDirection: 'column',
              gap: 8,
            }}
          >
            <Typography.Title level={4} withoutMargins>
              Certification review
            </Typography.Title>
            {r && (
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                <Tag componentId="gsb.certify.review" color={REVIEW_TAG[r.status].color}>
                  {REVIEW_TAG[r.status].label}
                </Tag>
                <Typography.Text>
                  Reviewer {r.reviewer}
                  {r.decidedAt
                    ? `, ${new Date(r.decidedAt).toLocaleString()}`
                    : `, asked ${new Date(r.createdAt).toLocaleString()}`}
                  {r.decisionComment ? `: "${r.decisionComment}"` : ''}
                </Typography.Text>
                {r.status === 'pending' && (
                  <>
                    <Button
                      componentId="gsb.certify.copy"
                      size="small"
                      onClick={() => void navigator.clipboard.writeText(`${window.location.origin}/reviews/${r.id}`)}
                    >
                      Copy the review link
                    </Button>
                    <Button
                      componentId="gsb.certify.cancel"
                      size="small"
                      disabled={!!busy}
                      onClick={() => post('cancel', 'certification/reviews/cancel', {})}
                    >
                      Cancel the request
                    </Button>
                  </>
                )}
              </div>
            )}
            {v.changed && <Typography.Text>The tables changed since the review. Ask for a new review.</Typography.Text>}
            {r?.status !== 'pending' && (r?.status !== 'approved' || v.changed) && (
              <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
                <div style={{ minWidth: 280 }}>
                  <FormUI.Label htmlFor="cert-reviewer">Reviewer email</FormUI.Label>
                  <Input
                    componentId="gsb.certify.reviewer"
                    id="cert-reviewer"
                    type="email"
                    placeholder="name@company.com"
                    value={reviewer}
                    onChange={(e) => setReviewer(e.target.value)}
                  />
                </div>
                <div style={{ flex: 1, minWidth: 240 }}>
                  <FormUI.Label htmlFor="cert-comment">Note for the reviewer (optional)</FormUI.Label>
                  <Input
                    componentId="gsb.certify.comment"
                    id="cert-comment"
                    maxLength={2000}
                    value={comment}
                    onChange={(e) => setComment(e.target.value)}
                  />
                </div>
                <Button
                  componentId="gsb.certify.request"
                  type="primary"
                  loading={busy === 'request'}
                  disabled={!!busy || !checked || !reviewer.trim()}
                  onClick={() =>
                    post('request', 'certification/reviews', { reviewer: reviewer.trim(), comment }, () => {
                      setReviewer('');
                      setComment('');
                    })
                  }
                >
                  Ask for certification
                </Button>
              </div>
            )}
            {!checked && <Typography.Text color="secondary">Run the data checks on each table first.</Typography.Text>}
            {v.statements.length > 0 && !allCertified && (
              <div>
                <Button componentId="gsb.certify.apply" type="primary" onClick={() => setExamining(true)}>
                  Set the certification tag
                </Button>
              </div>
            )}
            {allCertified && r?.status === 'approved' && (
              <Typography.Text>Each table has the certification tag.</Typography.Text>
            )}
            <Typography.Text color="secondary">
              The reviewer opens Reviews in this app and sees the data checks, the readiness checks and the descriptions
              as they were when you asked. The app does not send email, so send the reviewer the link.
            </Typography.Text>
          </section>
          {error && <Alert componentId="gsb.certify.error" type="error" closable={false} message={error} />}

          <Modal
            componentId="gsb.certify.apply_modal"
            title="Set the certification tag"
            visible={examining}
            okText="Run SQL"
            cancelText="Cancel"
            okButtonProps={{ loading: busy === 'apply' }}
            onCancel={() => setExamining(false)}
            onOk={() => post('apply', 'certification/apply', { statements: v.statements }, () => setExamining(false))}
          >
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <Alert
                componentId="gsb.certify.apply_warning"
                type="warning"
                closable={false}
                message="This changes Unity Catalog, as you. Other users and tools see the tag."
                description="You need the APPLY TAG privilege on each table, or you must own it, and the tag policy must let you set the value."
              />
              <SqlBlock label="SQL that runs" sql={v.statements.join(';\n')} />
            </div>
          </Modal>
        </div>
      )}
    </DataState>
  );
}
