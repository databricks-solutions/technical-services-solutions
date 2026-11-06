-- Restore an older version as a new one, import a metric view from Unity Catalog, and promote a version to UC.
ALTER TABLE gsb.metric_view_draft DROP CONSTRAINT metric_view_draft_origin_check;
ALTER TABLE gsb.metric_view_draft ADD CONSTRAINT metric_view_draft_origin_check
  CHECK (origin IN ('generated', 'refined', 'edited', 'pattern', 'template', 'restored', 'imported'));

-- The Unity Catalog view a sub-project promotes to, as catalog.schema.view.
ALTER TABLE gsb.project ADD COLUMN promotion_target text CHECK (length(promotion_target) BETWEEN 5 AND 800);

CREATE TABLE gsb.promotion (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES gsb.project (id) ON DELETE CASCADE,
  version integer NOT NULL,
  target text NOT NULL,
  yaml text NOT NULL,
  status text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'succeeded', 'failed')),
  error text,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz
);
CREATE INDEX promotion_project_idx ON gsb.promotion (project_id, created_at DESC);
