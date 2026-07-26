-- Correlated AI findings may describe multiple devices in one identity field.
-- Preserve the complete object in raw_finding and allow a bounded 512-character
-- searchable summary in the indexed identity column.
ALTER TABLE ai_findings
  MODIFY COLUMN device_ip VARCHAR(512) NULL;
