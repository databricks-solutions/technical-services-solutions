-- Approval before Promote: the author names one reviewer by email, who sees the sub-project read-only.
ALTER TABLE gsb.project ADD COLUMN require_approval boolean NOT NULL DEFAULT false;

CREATE TABLE gsb.review (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES gsb.project (id) ON DELETE CASCADE,
  version integer NOT NULL,
  reviewer text NOT NULL CHECK (length(reviewer) BETWEEN 3 AND 320),
  requested_by text NOT NULL,
  request_comment text CHECK (length(request_comment) <= 2000),
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
  decision_comment text CHECK (length(decision_comment) <= 2000),
  decided_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (lower(reviewer) <> lower(requested_by))
);
CREATE INDEX review_reviewer_idx ON gsb.review (lower(reviewer), status);
CREATE INDEX review_project_idx ON gsb.review (project_id, created_at DESC);
CREATE UNIQUE INDEX review_one_pending ON gsb.review (project_id) WHERE status = 'pending';
