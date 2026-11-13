-- The hash of the space settings that the app last sent, so the score can tell when the space is out of date.
ALTER TABLE gsb.genie_space ADD COLUMN config_hash text;
