-- A fix can need several statements (a primary key needs NOT NULL columns first).
-- The UI shows and the user approves the whole list; the runner executes each one separately.
ALTER TABLE gsb.recommendation DROP COLUMN statement;
ALTER TABLE gsb.recommendation
  ADD COLUMN source_id uuid REFERENCES gsb.source (id) ON DELETE CASCADE,
  ADD COLUMN statements text[] NOT NULL CHECK (cardinality(statements) BETWEEN 1 AND 200);
