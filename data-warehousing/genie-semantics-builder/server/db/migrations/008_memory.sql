-- The intake chat of each sub-project, so a reload or a later visit continues it.
CREATE TABLE gsb.chat_session (
  project_id uuid PRIMARY KEY REFERENCES gsb.project (id) ON DELETE CASCADE,
  messages jsonb NOT NULL,
  updated_by text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Business terms and assumptions shared by the sub-projects of a project, taken from confirmed briefs.
CREATE TABLE gsb.project_memory (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES gsb.project (id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('term', 'assumption')),
  text text NOT NULL,
  detail text,
  from_project_id uuid REFERENCES gsb.project (id) ON DELETE SET NULL,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, kind, text)
);

-- Briefs confirmed before memory existed: add their terms and assumptions once.
WITH latest AS (
  SELECT DISTINCT ON (b.project_id) b.project_id, b.content->'brief' AS brief, b.confirmed_by
  FROM gsb.semantic_brief b WHERE b.status = 'confirmed' ORDER BY b.project_id, b.version DESC
)
INSERT INTO gsb.project_memory (project_id, kind, text, detail, from_project_id, created_by)
SELECT COALESCE(p.parent_id, p.id), m.kind, m.text, m.detail, p.id, COALESCE(l.confirmed_by, p.created_by)
FROM latest l JOIN gsb.project p ON p.id = l.project_id
CROSS JOIN LATERAL (
  SELECT 'term' AS kind, g->>'term' AS text, g->>'definition' AS detail
  FROM jsonb_array_elements(COALESCE(l.brief->'glossary', '[]')) g
  UNION ALL
  SELECT 'assumption', a #>> '{}', NULL FROM jsonb_array_elements(COALESCE(l.brief->'assumptions', '[]')) a
) m
WHERE m.text IS NOT NULL AND m.text <> ''
ON CONFLICT (project_id, kind, text) DO NOTHING;
