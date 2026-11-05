-- A design can start from the template, built without a model call.
ALTER TABLE gsb.metric_view_draft DROP CONSTRAINT metric_view_draft_origin_check;
ALTER TABLE gsb.metric_view_draft ADD CONSTRAINT metric_view_draft_origin_check
  CHECK (origin IN ('generated', 'refined', 'edited', 'pattern', 'template'));
