-- Stress tests of a validated design: the queries the app ran and their Query History metrics. No data rows.

CREATE TABLE gsb.stress_run (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES gsb.project (id) ON DELETE CASCADE,
  version integer NOT NULL CHECK (version > 0),
  sandbox_view text NOT NULL,
  settings jsonb NOT NULL,
  status text NOT NULL DEFAULT 'running'
    CHECK (status IN ('running', 'stopping', 'stopped', 'finished', 'failed')),
  error text,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz
);

-- One run at a time per project.
CREATE UNIQUE INDEX stress_run_active ON gsb.stress_run (project_id) WHERE status IN ('running', 'stopping');
CREATE INDEX stress_run_project ON gsb.stress_run (project_id, created_at DESC);

CREATE TABLE gsb.stress_query (
  run_id uuid NOT NULL REFERENCES gsb.stress_run (id) ON DELETE CASCADE,
  position integer NOT NULL,
  query jsonb NOT NULL,
  sql text NOT NULL,
  attempts jsonb NOT NULL DEFAULT '[]',
  PRIMARY KEY (run_id, position)
);
