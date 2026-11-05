-- A materialization try is a stress run on a sandbox copy of the view with a materialization block.

ALTER TABLE gsb.stress_run ADD COLUMN materialization jsonb;
ALTER TABLE gsb.stress_run DROP CONSTRAINT stress_run_status_check;
ALTER TABLE gsb.stress_run ADD CONSTRAINT stress_run_status_check
  CHECK (status IN ('running', 'refreshing', 'stopping', 'stopped', 'finished', 'failed'));

DROP INDEX gsb.stress_run_active;
CREATE UNIQUE INDEX stress_run_active ON gsb.stress_run (project_id)
  WHERE status IN ('running', 'refreshing', 'stopping');

-- The materialization a query read, from EXPLAIN EXTENDED. NULL when it read the sources.
ALTER TABLE gsb.stress_query ADD COLUMN matched text;
