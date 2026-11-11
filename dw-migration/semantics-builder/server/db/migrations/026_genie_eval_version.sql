-- The design version a benchmark run measured, so the golden gate uses runs of the promoted version only.
ALTER TABLE gsb.genie_eval ADD COLUMN version integer;
