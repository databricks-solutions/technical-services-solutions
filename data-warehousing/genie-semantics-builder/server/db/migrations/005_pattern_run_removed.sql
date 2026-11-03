-- Set when the approved DROP of the pattern sandbox view succeeds.
ALTER TABLE gsb.pattern_run ADD COLUMN removed_at timestamptz;
