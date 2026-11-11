-- Optimize the Genie agent (phase i3): benchmark runs, and the changes a person approved.
-- A run keeps the counts and the assessment of each question, never result values.
CREATE TABLE gsb.genie_tuning (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES gsb.project (id) ON DELETE CASCADE,
  question text NOT NULL CHECK (length(question) BETWEEN 1 AND 1000),
  change jsonb NOT NULL,
  rationale text NOT NULL DEFAULT '',
  status text NOT NULL DEFAULT 'proposed'
    CHECK (status IN ('proposed', 'trying', 'kept', 'reverted', 'dismissed', 'failed')),
  before_correct integer,
  after_correct integer,
  num_questions integer,
  error text,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  decided_at timestamptz
);
CREATE INDEX genie_tuning_project_idx ON gsb.genie_tuning (project_id, created_at DESC);
-- One change on trial at a time.
CREATE UNIQUE INDEX genie_tuning_one_trying ON gsb.genie_tuning (project_id) WHERE status = 'trying';

CREATE TABLE gsb.genie_eval (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES gsb.project (id) ON DELETE CASCADE,
  space_id text NOT NULL,
  eval_run_id text NOT NULL,
  config_hash text NOT NULL,
  tuning_id uuid REFERENCES gsb.genie_tuning (id) ON DELETE SET NULL,
  status text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'done', 'failed')),
  num_questions integer NOT NULL DEFAULT 0,
  num_correct integer NOT NULL DEFAULT 0,
  num_needs_review integer NOT NULL DEFAULT 0,
  -- [{question, assessment, resultId}]
  results jsonb NOT NULL DEFAULT '[]',
  error text,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz
);
CREATE INDEX genie_eval_project_idx ON gsb.genie_eval (project_id, created_at DESC);
CREATE UNIQUE INDEX genie_eval_one_running ON gsb.genie_eval (project_id) WHERE status = 'running';
