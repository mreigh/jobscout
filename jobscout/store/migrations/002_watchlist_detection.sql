-- 002: watchlist fields and ATS detection state

ALTER TABLE companies ADD COLUMN why_fit TEXT;
ALTER TABLE companies ADD COLUMN roles_to_watch TEXT;
ALTER TABLE companies ADD COLUMN warm_angle TEXT;
ALTER TABLE companies ADD COLUMN ats_hint TEXT;          -- what the watchlist said (may be 'auto-detect')
ALTER TABLE companies ADD COLUMN active INTEGER NOT NULL DEFAULT 1;  -- 0 = removed from watchlist
ALTER TABLE companies ADD COLUMN detect_status TEXT;     -- found, override, not_found, error, needs_url
ALTER TABLE companies ADD COLUMN detect_confidence TEXT; -- confirmed, likely, review
ALTER TABLE companies ADD COLUMN detect_detail TEXT;     -- JSON: every hit and miss, for debugging
ALTER TABLE companies ADD COLUMN job_count INTEGER;      -- open postings seen at detection time

-- History of ATS changes, so migrations between vendors get noticed (JS-014)
CREATE TABLE ats_changes (
    id          INTEGER PRIMARY KEY,
    company_id  INTEGER NOT NULL REFERENCES companies(id),
    old_ats     TEXT,
    old_token   TEXT,
    new_ats     TEXT,
    new_token   TEXT,
    changed_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
