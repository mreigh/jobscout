-- 003: job collection (E2) and job lifecycle (E4)

ALTER TABLE jobs ADD COLUMN source TEXT;            -- ats the posting came from
ALTER TABLE jobs ADD COLUMN external_id TEXT;       -- the ats's own id for the posting
ALTER TABLE jobs ADD COLUMN department TEXT;
ALTER TABLE jobs ADD COLUMN posted_at TEXT;         -- when the company says it was posted (approx for Workday)
ALTER TABLE jobs ADD COLUMN comp_source TEXT;       -- 'ats' (structured) or 'text' (parsed from the description)
ALTER TABLE jobs ADD COLUMN updated_at TEXT;        -- last time title/description/comp changed
CREATE INDEX idx_jobs_open ON jobs(company_id, closed_at);

ALTER TABLE companies ADD COLUMN collected_at TEXT;
ALTER TABLE companies ADD COLUMN collect_status TEXT;  -- ok, error, unsupported
ALTER TABLE companies ADD COLUMN collect_detail TEXT;
ALTER TABLE companies ADD COLUMN open_jobs INTEGER;
