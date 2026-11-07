-- Table metadata (names, types, comments, keys) behind each report, so scores and gains are recomputed without the warehouse.
ALTER TABLE gsb.readiness_report ADD COLUMN profile jsonb;
-- What each fix changes in that metadata, to compute its score gain.
ALTER TABLE gsb.recommendation ADD COLUMN effect jsonb;
