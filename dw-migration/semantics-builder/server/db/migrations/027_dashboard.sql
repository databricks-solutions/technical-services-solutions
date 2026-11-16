-- The starter AI/BI dashboard of a sub-project (phase h6), made on its promoted view as the user.
CREATE TABLE gsb.dashboard (
  project_id uuid PRIMARY KEY REFERENCES gsb.project (id) ON DELETE CASCADE,
  dashboard_id text NOT NULL CHECK (length(dashboard_id) BETWEEN 1 AND 100),
  path text,
  view_name text NOT NULL,
  version integer NOT NULL,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
