-- Ask Genie One (OneChat) next to the Genie space: which engine answered, and what Genie One read.
ALTER TABLE gsb.genie_check
  ADD COLUMN engine text NOT NULL DEFAULT 'space' CHECK (engine IN ('space', 'one')),
  ADD COLUMN read jsonb;
