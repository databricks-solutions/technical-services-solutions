-- Drift checks of promoted views: findings and a snapshot (owner, grants, column types; no result values).
CREATE TABLE gsb.drift_check (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES gsb.project (id) ON DELETE CASCADE,
  target text NOT NULL,
  findings jsonb NOT NULL,
  snapshot jsonb NOT NULL,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX drift_check_project_idx ON gsb.drift_check (project_id, created_at DESC);

-- Opt-in data drift: measure totals of the promoted view at one time, set by the user.
ALTER TABLE gsb.project ADD COLUMN data_baseline jsonb;
