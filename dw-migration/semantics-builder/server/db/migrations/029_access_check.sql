-- The tests of the promoted view, run as one person (the owner or a reviewer with restricted access).
-- Only pass or fail, the row count and the difference in percent: never result values.
CREATE TABLE gsb.access_check (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES gsb.project (id) ON DELETE CASCADE,
  version integer NOT NULL,
  target text NOT NULL,
  run_by text NOT NULL,
  results jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX access_check_project ON gsb.access_check (project_id, version, run_by, created_at DESC);
