import { useState } from 'react';
import { Alert, Button, Checkbox, FormUI, Input, Tag, Typography } from '@databricks/design-system';
import type { ApprovalState, Review } from '../../../shared/review';
import { api } from '../api';

export const REVIEW_TAG: Record<Review['status'], { color: 'lemon' | 'teal' | 'coral' | 'default'; label: string }> = {
  pending: { color: 'lemon', label: 'Waiting for review' },
  approved: { color: 'teal', label: 'Approved' },
  rejected: { color: 'coral', label: 'Rejected' },
  cancelled: { color: 'default', label: 'Cancelled' },
};

/** True when Promote of this version can run under the approval rule. */
export const approved = (s: ApprovalState | undefined, version: number | undefined) =>
  !s?.required || (s.review?.status === 'approved' && s.review.version === version);

/** Whether Promote needs approval, the latest review, and the form to ask a reviewer. */
export function ApprovalPanel({
  projectId,
  state,
  version,
  onChange,
}: {
  projectId: string;
  state: ApprovalState;
  /** The latest validated version, when one can be promoted. */
  version: number | undefined;
  onChange: (s: ApprovalState) => void;
}) {
  const [reviewer, setReviewer] = useState('');
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [copied, setCopied] = useState(false);
  const r = state.review;
  const pendingThis = r?.status === 'pending' && r.version === version;
  const link = r ? `${window.location.origin}/reviews/${r.id}` : '';

  const post = (path: string, body: unknown, after?: () => void) => {
    setBusy(true);
    setError(undefined);
    api<ApprovalState>(`/api/projects/${projectId}/${path}`, body).then(
      (next) => {
        setBusy(false);
        onChange(next);
        after?.();
      },
      (err: unknown) => {
        setBusy(false);
        setError((err as Error).message);
      }
    );
  };

  return (
    <div
      style={{
        border: '1px solid var(--db-border-base)',
        borderRadius: 8,
        padding: 12,
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
      }}
    >
      <Checkbox
        componentId="gsb.approval.required"
        isChecked={state.required}
        disabled={busy}
        onChange={(on) => post('approval', { required: on })}
      >
        Promote needs approval by another person
      </Checkbox>
      {r && (
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <Tag componentId="gsb.approval.status" color={REVIEW_TAG[r.status].color}>
            {REVIEW_TAG[r.status].label}
          </Tag>
          <Typography.Text>
            Version {r.version}, reviewer {r.reviewer}
            {r.decidedAt
              ? `, ${new Date(r.decidedAt).toLocaleString()}`
              : `, asked ${new Date(r.createdAt).toLocaleString()}`}
            {r.decisionComment ? `: "${r.decisionComment}"` : ''}
          </Typography.Text>
          {r.status === 'pending' && (
            <>
              <Button
                componentId="gsb.approval.copy"
                size="small"
                onClick={() =>
                  void navigator.clipboard.writeText(link).then(() => {
                    setCopied(true);
                    setTimeout(() => setCopied(false), 2000);
                  })
                }
              >
                {copied ? 'Copied' : 'Copy the review link'}
              </Button>
              <Button
                componentId="gsb.approval.cancel"
                size="small"
                disabled={busy}
                onClick={() => post('reviews/cancel', {})}
              >
                Cancel the request
              </Button>
            </>
          )}
        </div>
      )}
      {state.required && version !== undefined && !approved(state, version) && !pendingThis && (
        <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div style={{ minWidth: 280 }}>
            <FormUI.Label htmlFor="ap-reviewer">Reviewer email</FormUI.Label>
            <Input
              componentId="gsb.approval.reviewer"
              id="ap-reviewer"
              type="email"
              placeholder="name@company.com"
              value={reviewer}
              onChange={(e) => setReviewer(e.target.value)}
            />
          </div>
          <div style={{ flex: 1, minWidth: 240 }}>
            <FormUI.Label htmlFor="ap-comment">Note for the reviewer (optional)</FormUI.Label>
            <Input
              componentId="gsb.approval.comment"
              id="ap-comment"
              maxLength={2000}
              value={comment}
              onChange={(e) => setComment(e.target.value)}
            />
          </div>
          <Button
            componentId="gsb.approval.request"
            type="primary"
            loading={busy}
            disabled={!reviewer.trim()}
            onClick={() =>
              post('reviews', { reviewer: reviewer.trim(), comment }, () => {
                setReviewer('');
                setComment('');
              })
            }
          >
            Ask for approval of version {version}
          </Button>
        </div>
      )}
      {state.required && (
        <Typography.Text color="secondary">
          The reviewer opens Reviews in this app and sees this version read-only: the YAML, the tests and the impact.
          The app does not send email, so send the reviewer the link.
        </Typography.Text>
      )}
      {error && <Alert componentId="gsb.approval.error" type="error" closable={false} message={error} />}
    </div>
  );
}
