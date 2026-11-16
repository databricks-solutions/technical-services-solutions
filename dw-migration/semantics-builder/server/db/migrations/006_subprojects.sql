-- A project groups sub-projects. A sub-project is one metric view with its own brief, sources and designs,
-- so every existing table keeps pointing at gsb.project, now a sub-project.
ALTER TABLE gsb.project ADD COLUMN parent_id uuid REFERENCES gsb.project (id) ON DELETE CASCADE;
ALTER TABLE gsb.project ADD CONSTRAINT project_not_own_parent CHECK (parent_id IS DISTINCT FROM id);
CREATE INDEX project_parent_idx ON gsb.project (parent_id);

-- Each existing project becomes the only sub-project of a new parent with the same name.
WITH m AS MATERIALIZED (
  SELECT id AS child, gen_random_uuid() AS parent, name, description, created_by, created_at FROM gsb.project
), ins AS (
  INSERT INTO gsb.project (id, name, description, created_by, created_at)
  SELECT parent, name, description, created_by, created_at FROM m
)
UPDATE gsb.project p SET parent_id = m.parent FROM m WHERE p.id = m.child;
