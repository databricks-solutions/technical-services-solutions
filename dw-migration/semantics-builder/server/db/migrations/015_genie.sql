-- Ask Genie: one Genie space per sub-project on its sandbox view, and the questions asked with their verdicts.
CREATE TABLE gsb.genie_space (
  project_id uuid PRIMARY KEY REFERENCES gsb.project (id) ON DELETE CASCADE,
  space_id text NOT NULL CHECK (length(space_id) BETWEEN 1 AND 100),
  view_name text NOT NULL,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE gsb.genie_check (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES gsb.project (id) ON DELETE CASCADE,
  version integer NOT NULL,
  question text NOT NULL CHECK (length(question) BETWEEN 1 AND 1000),
  expected jsonb,
  verdict text NOT NULL CHECK (verdict IN ('matches', 'different', 'no_answer', 'needs_review', 'error')),
  detail text NOT NULL DEFAULT '',
  answer text NOT NULL DEFAULT '',
  sql text,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX genie_check_project_idx ON gsb.genie_check (project_id, created_at DESC);
