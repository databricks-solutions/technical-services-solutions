-- The production Genie agent belongs to the top-level project: one Genie space on the promoted views of the
-- sub-projects that the author chooses. It replaces the per-sub-project table of 024.
DROP TABLE gsb.genie_agent;
CREATE TABLE gsb.genie_agent (
  project_id uuid PRIMARY KEY REFERENCES gsb.project (id) ON DELETE CASCADE,
  space_id text NOT NULL CHECK (length(space_id) BETWEEN 1 AND 100),
  sub_projects uuid[] NOT NULL CHECK (cardinality(sub_projects) BETWEEN 1 AND 20),
  config_hash text NOT NULL,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
