-- Pattern runs keep metadata only: status, row count and the SQL. Never result values.

ALTER TABLE gsb.metric_view_draft DROP CONSTRAINT metric_view_draft_origin_check;
ALTER TABLE gsb.metric_view_draft ADD CONSTRAINT metric_view_draft_origin_check
  CHECK (origin IN ('generated', 'refined', 'edited', 'pattern'));

CREATE TABLE gsb.pattern_run (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES gsb.project (id) ON DELETE CASCADE,
  slug text NOT NULL CHECK (slug ~ '^[a-z][a-z0-9_]{0,40}$'),
  sandbox_view text NOT NULL,
  statements text[] NOT NULL CHECK (cardinality(statements) BETWEEN 1 AND 10),
  status text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'passed', 'failed')),
  test_sql text NOT NULL,
  rows_compared integer NOT NULL DEFAULT 0,
  detail text,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz
);
CREATE INDEX pattern_run_project_idx ON gsb.pattern_run (project_id, slug, created_at DESC);
