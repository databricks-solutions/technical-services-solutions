-- The idea cards and quick replies of the last chat turn, so they show again after a reload.
ALTER TABLE gsb.chat_session ADD COLUMN last_turn jsonb;
