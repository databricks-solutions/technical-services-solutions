-- Pages for UC Semantics Discover: the domain of a top-level project, and the user's edits to generated Pages.
ALTER TABLE gsb.project ADD COLUMN pages_domain text CHECK (length(pages_domain) BETWEEN 1 AND 200);

CREATE TABLE gsb.page_edit (
  project_id uuid NOT NULL REFERENCES gsb.project (id) ON DELETE CASCADE,
  key text NOT NULL CHECK (length(key) BETWEEN 1 AND 300),
  content jsonb NOT NULL,
  updated_by text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (project_id, key)
);
