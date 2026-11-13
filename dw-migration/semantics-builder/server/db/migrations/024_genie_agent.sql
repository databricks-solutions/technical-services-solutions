-- The production Genie agent (phase i4): one Genie space per sub-project on its promoted view.
CREATE TABLE gsb.genie_agent (
  project_id uuid PRIMARY KEY REFERENCES gsb.project (id) ON DELETE CASCADE,
  space_id text NOT NULL CHECK (length(space_id) BETWEEN 1 AND 100),
  view_name text NOT NULL,
  version integer NOT NULL,
  config_hash text NOT NULL,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
