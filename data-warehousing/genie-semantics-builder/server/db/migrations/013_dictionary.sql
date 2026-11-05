-- The metric dictionary of a project: imported definitions every sub-project reuses. Text only, no file.
CREATE TABLE gsb.dictionary_entry (
  project_id uuid NOT NULL REFERENCES gsb.project (id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('metric', 'dimension', 'term')),
  name text NOT NULL CHECK (length(name) BETWEEN 1 AND 4000),
  entry jsonb NOT NULL,
  source_file text NOT NULL,
  imported_by text NOT NULL,
  imported_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX dictionary_entry_name ON gsb.dictionary_entry (project_id, kind, lower(name));
