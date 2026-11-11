import { useState } from 'react';
import type { MouseEvent } from 'react';
import { useNavigate, useParams } from 'react-router';
import {
  Alert,
  Button,
  FormUI,
  Input,
  Table,
  TableCell,
  TableHeader,
  TableRow,
  Tag,
  Typography,
} from '@databricks/design-system';
import type { TestResult } from '../../../shared/designer';
import type { Review, ReviewDetail, ReviewList } from '../../../shared/review';
import { api, useResource } from '../api';
import { REVIEW_TAG } from '../components/ApprovalPanel';
import { ChecksTable } from '../components/CertifyPanel';
import { DataState } from '../components/DataState';
import { ImpactPanel } from '../components/ImpactPanel';
import { SqlBlock } from '../components/SqlBlock';
import { subPath } from './ProjectsPage';

const RESULT: Record<TestResult['status'], { color: 'teal' | 'coral'; label: string }> = {
  passed: { color: 'teal', label: 'Passed' },
  failed: { color: 'coral', label: 'Failed' },
  error: { color: 'coral', label: 'Error' },
};

function ReviewTable({ label, rows, who }: { label: string; rows: Review[]; who: 'reviewer' | 'requestedBy' }) {
  const navigate = useNavigate();
  const open = (id: string) => (e: MouseEvent) => {
    e.preventDefault();
    void navigate(`/reviews/${id}`);
  };
  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <Typography.Title level={3} withoutMargins>
        {label}
      </Typography.Title>
      {rows.length === 0 ? (
        <Typography.Text color="secondary">None.</Typography.Text>
      ) : (
        <Table aria-label={label}>
          <TableRow isHeader>
            <TableHeader componentId="gsb.reviews.h_sub">Sub-project</TableHeader>
            <TableHeader componentId="gsb.reviews.h_version">What</TableHeader>
            <TableHeader componentId="gsb.reviews.h_who">{who === 'reviewer' ? 'Reviewer' : 'Asked by'}</TableHeader>
            <TableHeader componentId="gsb.reviews.h_status">Status</TableHeader>
            <TableHeader componentId="gsb.reviews.h_when">Asked</TableHeader>
          </TableRow>
          {rows.map((r) => (
            <TableRow key={r.id}>
              <TableCell>
                <Typography.Link componentId="gsb.reviews.open" href={`/reviews/${r.id}`} onClick={open(r.id)}>
                  {r.project} / {r.subProject}
                </Typography.Link>
              </TableCell>
              <TableCell>{r.kind === 'data' ? 'Data certification' : `Version ${r.version}`}</TableCell>
              <TableCell>{r[who]}</TableCell>
              <TableCell>
                <Tag componentId="gsb.reviews.status" color={REVIEW_TAG[r.status].color}>
                  {REVIEW_TAG[r.status].label}
                </Tag>
              </TableCell>
              <TableCell>{new Date(r.createdAt).toLocaleString()}</TableCell>
            </TableRow>
          ))}
        </Table>
      )}
    </section>
  );
}

/** Reviews you were asked for, and the ones you asked for. */
export function ReviewsPage() {
  const data = useResource<ReviewList>('/api/reviews');
  return (
    <DataState status={data.status} message={data.error} onRetry={data.reload}>
      {data.data && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24, maxWidth: 1100 }}>
          <Typography.Text color="secondary">
            An author can ask you to approve a version before it goes to Unity Catalog, or to certify the tables of a
            sub-project. You see it read-only, and only what you were asked about.
          </Typography.Text>
          <ReviewTable label="For you to review" rows={data.data.toMe} who="requestedBy" />
          <ReviewTable label="You asked" rows={data.data.byMe} who="reviewer" />
        </div>
      )}
    </DataState>
  );
}

/** One review, read-only: the impact, the tests, the YAML and the SQL. The reviewer approves or rejects it. */
export function ReviewPage() {
  const { reviewId = '' } = useParams();
  const navigate = useNavigate();
  const data = useResource<ReviewDetail>(`/api/reviews/${reviewId}`);
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const d = data.data;
  const r = d?.review;

  const decide = (decision: 'approved' | 'rejected') => {
    setBusy(true);
    setError(undefined);
    api<Review>(`/api/reviews/${reviewId}/decision`, { decision, comment }).then(
      () => {
        setBusy(false);
        data.reload();
      },
      (err: unknown) => {
        setBusy(false);
        setError((err as Error).message);
      }
    );
  };

  return (
    <DataState status={data.status} message={data.error} onRetry={data.reload}>
      {d && r && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 1100 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <Typography.Title level={3} withoutMargins>
              {r.project} / {r.subProject}, {r.kind === 'data' ? 'data certification' : `version ${r.version}`}
            </Typography.Title>
            <Tag componentId="gsb.review.status" color={REVIEW_TAG[r.status].color}>
              {REVIEW_TAG[r.status].label}
            </Tag>
          </div>
          <Typography.Text>
            Asked by {r.requestedBy} on {new Date(r.createdAt).toLocaleString()}, reviewer {r.reviewer}.
            {r.kind === 'view' && (
              <>
                {' '}
                Target: <span style={{ wordBreak: 'break-all' }}>{r.target ?? 'not set'}</span>.
              </>
            )}
          </Typography.Text>
          {r.requestComment && <Typography.Text>{`Note: "${r.requestComment}"`}</Typography.Text>}
          {r.decidedAt && r.status !== 'pending' && (
            <Typography.Text>
              {REVIEW_TAG[r.status].label} on {new Date(r.decidedAt).toLocaleString()}
              {r.decisionComment ? `: "${r.decisionComment}"` : '.'}
            </Typography.Text>
          )}
          {r.status === 'pending' && !d.canDecide && (
            <div>
              <Button
                componentId="gsb.review.open_project"
                onClick={() =>
                  void navigate(
                    subPath(
                      r.parentId,
                      r.projectId,
                      r.kind === 'data' ? 'sources?tab=certification' : 'publish?section=promotion'
                    )
                  )
                }
              >
                Open the sub-project
              </Button>
            </div>
          )}

          {d.data ? (
            <>
              <Typography.Text>
                {`Approve when the data is fit to build on. Approve lets the author set the tag 'system.certification_status' = 'certified' on these ${d.data.tables.length} tables. The checks show counts and shares only, never values.`}
              </Typography.Text>
              {d.data.tables.map((t) => (
                <section
                  key={t.fullName}
                  aria-label={t.fullName}
                  style={{ display: 'flex', flexDirection: 'column', gap: 8 }}
                >
                  <Typography.Title level={4} withoutMargins>
                    {t.fullName}
                  </Typography.Title>
                  <Typography.Text>
                    {t.comment ? `Description: ${t.comment}` : 'The table has no description.'}
                  </Typography.Text>
                  <Typography.Text color="secondary" size="sm">
                    Data checked by {t.data.checkedBy} on {new Date(t.data.checkedAt).toLocaleString()}. Readiness
                    score: {t.readinessScore ?? 'none'}.
                  </Typography.Text>
                  <ChecksTable label={`Data checks of ${t.fullName}`} checks={t.data.checks} />
                  <ChecksTable label={`Readiness checks of ${t.fullName}`} checks={t.readiness} />
                  <Table aria-label={`Columns of ${t.fullName}`}>
                    <TableRow isHeader>
                      <TableHeader componentId="gsb.review.h_col">Column</TableHeader>
                      <TableHeader componentId="gsb.review.h_type">Type</TableHeader>
                      <TableHeader componentId="gsb.review.h_desc">Description</TableHeader>
                    </TableRow>
                    {t.columns.map((c) => (
                      <TableRow key={c.name}>
                        <TableCell>{c.name}</TableCell>
                        <TableCell>{c.type}</TableCell>
                        <TableCell>{c.comment || 'none'}</TableCell>
                      </TableRow>
                    ))}
                  </Table>
                </section>
              ))}
            </>
          ) : (
            <>
              <ImpactPanel path={`/api/reviews/${reviewId}/impact`} />

              <section style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <Typography.Title level={4} withoutMargins>
                  Tests
                </Typography.Title>
                {d.validation?.version === r.version ? (
                  d.validation.results.map((t) => (
                    <div key={t.name} style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
                      <Tag componentId="gsb.review.test" color={RESULT[t.status].color}>
                        {RESULT[t.status].label}
                      </Tag>
                      <Typography.Text bold>{t.name}</Typography.Text>
                      <Typography.Text>{t.detail}</Typography.Text>
                    </div>
                  ))
                ) : (
                  <>
                    <Typography.Text>
                      {`Version ${r.version} has no test run of its own. A restored version keeps the validated status of the version it copies. Its tests:`}
                    </Typography.Text>
                    <ul style={{ margin: 0, paddingLeft: 20 }}>
                      {d.tests.map((t) => (
                        <li key={t.name}>{t.name}</li>
                      ))}
                    </ul>
                  </>
                )}
              </section>

              <SqlBlock label="New YAML" sql={d.yaml} />
              {d.ucYaml && <SqlBlock label="YAML in Unity Catalog now" sql={d.ucYaml} />}
              {d.statement && <SqlBlock label="SQL that Promote runs" sql={d.statement} />}
            </>
          )}

          {d.canDecide && (
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
              <FormUI.Label htmlFor="rv-comment">Comment (needed to reject)</FormUI.Label>
              <Input.TextArea
                componentId="gsb.review.comment"
                id="rv-comment"
                rows={3}
                maxLength={2000}
                value={comment}
                onChange={(e) => setComment(e.target.value)}
              />
              <div style={{ display: 'flex', gap: 8 }}>
                <Button
                  componentId="gsb.review.approve"
                  type="primary"
                  loading={busy}
                  onClick={() => decide('approved')}
                >
                  {r.kind === 'data' ? 'Approve the tables' : `Approve version ${r.version}`}
                </Button>
                <Button
                  componentId="gsb.review.reject"
                  danger
                  disabled={busy || !comment.trim()}
                  onClick={() => decide('rejected')}
                >
                  Reject
                </Button>
              </div>
              <Typography.Text color="secondary">
                {r.kind === 'data'
                  ? 'Approve lets the author set the certification tag. It does not set it.'
                  : 'Approve lets the author promote this version. It does not promote it.'}
              </Typography.Text>
            </section>
          )}
          {error && <Alert componentId="gsb.review.error" type="error" closable={false} message={error} />}
        </div>
      )}
    </DataState>
  );
}
