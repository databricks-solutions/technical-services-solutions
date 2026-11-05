-- Metric view definitions are metadata: YAML text, explanations and test results, never data rows.

CREATE TABLE gsb.metric_view_draft (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES gsb.project (id) ON DELETE CASCADE,
  version integer NOT NULL CHECK (version > 0),
  name text NOT NULL CHECK (length(name) BETWEEN 1 AND 255),
  yaml text NOT NULL CHECK (length(yaml) BETWEEN 1 AND 200000),
  explanations jsonb NOT NULL DEFAULT '{}',
  tests jsonb NOT NULL DEFAULT '[]',
  issues jsonb NOT NULL DEFAULT '[]',
  origin text NOT NULL CHECK (origin IN ('generated', 'refined', 'edited')),
  status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'validated')),
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, version)
);

CREATE TABLE gsb.validation_run (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  draft_id uuid NOT NULL REFERENCES gsb.metric_view_draft (id) ON DELETE CASCADE,
  sandbox_view text NOT NULL,
  statements text[] NOT NULL CHECK (cardinality(statements) BETWEEN 1 AND 10),
  status text NOT NULL DEFAULT 'proposed'
    CHECK (status IN ('proposed', 'running', 'passed', 'failed', 'rejected')),
  results jsonb NOT NULL DEFAULT '[]',
  error text,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz
);
CREATE INDEX validation_run_draft_idx ON gsb.validation_run (draft_id, created_at DESC);
