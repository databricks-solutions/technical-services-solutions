-- Data certification (phase i1): the data check results of each source, and a review of the tables.
-- The checks keep counts, shares and column names only, never a value of the data.
ALTER TABLE gsb.source
  ADD COLUMN data_checks jsonb,
  ADD COLUMN data_checked_at timestamptz,
  ADD COLUMN data_checked_by text;

-- A review is of a view version, or of the data: the tables, their checks and descriptions at request time.
ALTER TABLE gsb.review ADD COLUMN kind text NOT NULL DEFAULT 'view' CHECK (kind IN ('view', 'data'));
ALTER TABLE gsb.review ADD COLUMN snapshot jsonb;
ALTER TABLE gsb.review ALTER COLUMN version DROP NOT NULL;
ALTER TABLE gsb.review ADD CONSTRAINT review_kind_shape
  CHECK ((kind = 'view' AND version IS NOT NULL) OR (kind = 'data' AND snapshot IS NOT NULL));
DROP INDEX gsb.review_one_pending;
CREATE UNIQUE INDEX review_one_pending ON gsb.review (project_id, kind) WHERE status = 'pending';
