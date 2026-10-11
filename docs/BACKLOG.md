# JobScout Backlog

**Priority:** P0 = needed for the milestone · P1 = should have · P2 = later / nice to have
**Size:** S = an evening · M = a weekend day · L = multiple sessions

## Milestones

| Milestone | Outcome | Epics |
|---|---|---|
| **M1: First signal** | `jobscout collect` pulls live postings from the big public ATS APIs for the watchlist and prints new roles | E0, E1, E2 (core), E4 |
| **M2: Useful every morning** | Filtered, scored digest lands in the inbox daily without anyone touching it | E5, E8, E9 |
| **M3: Warm and clean** | Every role shows who you know there; nothing already applied to ever shows up | E3, E6, E7 |
| **M4: Showcase** | Public repo with demo mode, docs, architecture diagram, and a measured scoring eval | E10 |
| **Later** | Signals before a req exists, feedback loop, ghost detection | E11 |

---

## E0: Foundation ✅ Done Oct 9, 2026

| ID | Story | Pri | Size | Acceptance criteria |
|---|---|---|---|---|
| JS-001 | Create repo, `pyproject.toml`, package skeleton, `.gitignore` for `profile/`, `.env`, `*.db` | P0 | S | `pip install -e .` works; personal files can't be committed by accident |
| JS-002 | Config loading: `.env` for secrets, `config/*.yaml` for rules, typed with pydantic | P0 | S | Missing or bad config fails fast with a clear message |
| JS-003 | SQLite store with schema for companies, raw postings, jobs, scores, runs | P0 | M | Schema created on first run; migrations versioned |
| JS-004 | CLI shell with `typer` (`detect`, `collect`, `run`, `digest`) | P0 | S | `jobscout --help` lists commands |
| JS-005 | Structured logging + per-run record (start, end, counts, errors) | P1 | S | Every run writes a row to `runs` |
| JS-006 | Test harness with recorded HTTP fixtures; GitHub Actions CI | P1 | S | Tests run offline in CI on every push |

## E1: Watchlist and ATS detection ✅ Done Oct 10, 2026

| ID | Story | Pri | Size | Acceptance criteria |
|---|---|---|---|---|
| JS-010 | Import watchlist from `profile/watchlist.xlsx` (or .csv) | P0 | S | All 114 companies load with tier, segment, status, ATS |
| JS-011 | ATS detector: probe Greenhouse, Lever, Ashby, SmartRecruiters, Workable with candidate slugs derived from company name | P0 | M | Detected ATS + board token saved per company; unresolved companies listed for manual entry |
| JS-012 | Workday support from a pasted careers URL (tenant + site parsed, verified via API) | P1 | M | Tenant + site captured for Workday companies |
| JS-013 | Manual override column so a hand-entered board URL always wins | P0 | S | Override respected on every run |
| JS-014 | Weekly re-detection to catch ATS migrations and dead boards | P2 | S | Changes logged and shown in the digest health section |

## E2: Collectors (core ✅ Oct 11, 2026; JS-027/028 open)

| ID | Story | Pri | Size | Acceptance criteria |
|---|---|---|---|---|
| JS-020 | ✅ Collector interface: every collector returns a list of `RawPosting` with source, URL, title, location, description, posted date, comp if present | P0 | S | Interface documented; one shared test suite |
| JS-021 | ✅ Greenhouse collector | P0 | S | Pulls all postings with full descriptions for a board |
| JS-022 | ✅ Lever collector | P0 | S | Same |
| JS-023 | ✅ Ashby collector, including comp when published | P0 | S | Same, comp parsed into min/max |
| JS-024 | ✅ SmartRecruiters collector | P1 | S | Same |
| JS-025 | ✅ Workable collector | P1 | S | Same |
| JS-026 | ✅ Workday collector (paged JSON search + detail fetch) | P1 | L | Handles paging and per-tenant quirks for FIS, Associated, NM, CLA |
| JS-027 | Generic careers-page fallback: fetch HTML, extract postings with Claude into the `RawPosting` shape | P2 | M | Works on at least 3 non-standard sites; strict rate limit |
| JS-028 | Staffing board collectors (Kforce, Apex, Beacon Hill) filtered to WI + remote FS | P2 | M | Only local or remote fintech-relevant results kept |
| JS-029 | ✅ (shipped early in E1) Per-host rate limiting, retries with backoff, honest user agent | P0 | S | No host hit more than N times per minute; failures don't kill the run |

## E3: Email alert ingestion

| ID | Story | Pri | Size | Acceptance criteria |
|---|---|---|---|---|
| JS-030 | Set up LinkedIn and Indeed saved-search alerts routed to a Gmail label | P1 | S | Alerts land under one label (manual setup step, documented) |
| JS-031 | Gmail API reader with read-only scope, limited to the alerts label | P1 | M | Only that label is read; processed messages tracked |
| JS-032 | Alert parsers for LinkedIn and Indeed emails into `RawPosting` | P1 | M | Title, company, location, link extracted from real samples |
| JS-033 | Resolve alert links back to the company's own ATS posting when possible | P2 | M | Alert jobs merge with the matching ATS record |

## E4: Normalize and dedupe ✅ Done Oct 11, 2026 (title synonyms deferred to E5)

| ID | Story | Pri | Size | Acceptance criteria |
|---|---|---|---|---|
| JS-040 | ◐ Normalize remote/hybrid flags and comp (done); title synonyms like Sr./Senior move to E5 filters | P0 | M | "Sr." / "Senior", "Remote - US" / "United States (Remote)" etc. collapse consistently |
| JS-041 | ✅ Job fingerprint per board posting (cross-source merge with email alerts lands with E3) | P0 | M | Same role from two sources appears once |
| JS-042 | ✅ New / updated / closed detection between runs | P0 | S | Digest can say "new today" and "closed since yesterday" |
| JS-043 | ✅ Store raw payloads for replay | P1 | S | `jobscout rescore` works without re-fetching |

## E5: Filtering and fit scoring

| ID | Story | Pri | Size | Acceptance criteria |
|---|---|---|---|---|
| JS-050 | `filters.yaml` hard rules: location, comp floor, include/exclude title keywords, exclusion phrases | P0 | M | Each dropped job records which rule dropped it |
| JS-051 | `candidate.yaml` profile: verified history, target lanes, dealbreakers, IC vs. leader preference | P0 | M | Built only from verified facts; gitignored; sample version committed |
| JS-052 | Claude fit scorer: score, recommendation, why-it-fits, gap flags, level read, as structured JSON | P0 | M | Output validated against a schema; invalid responses retried once then flagged |
| JS-053 | Score caching by fingerprint + description hash | P0 | S | Unchanged jobs never re-scored |
| JS-054 | Tier weighting: A-tier companies surface at a lower score threshold | P1 | S | Threshold per tier in config |
| JS-055 | **Scoring eval set** built from real past decisions (applied, interviewed, rejected, passed) | P1 | M | ~30 labeled JDs; eval script reports agreement between scorer and actual decisions |
| JS-056 | Cost tracking per run | P1 | S | Tokens and $ logged; daily run stays under budget |

## E6: Warm paths

| ID | Story | Pri | Size | Acceptance criteria |
|---|---|---|---|---|
| JS-060 | Import LinkedIn `Connections.csv` | P1 | S | Connections stored locally, never committed |
| JS-061 | Fuzzy company matching (handles "FIS" vs "FIS Global", "Fiserv, Inc.", acquisitions) | P1 | M | Match rate checked by hand on the watchlist; alias table for misses |
| JS-062 | Manual warm-contact notes from the watchlist (champions, recruiters, alumni) merged in | P1 | S | Known contacts show even if they aren't LinkedIn connections |
| JS-063 | "Network first" recommendation when a strong contact exists | P2 | S | Digest suggests the intro before the application |

## E7: Tracker sync

| ID | Story | Pri | Size | Acceptance criteria |
|---|---|---|---|---|
| JS-070 | Read the Google Sheet application tracker | P1 | M | Applied/rejected/passed roles suppressed from the digest |
| JS-071 | Match tracker rows to jobs (company + fuzzy title + date window) | P1 | M | No role already in the tracker reappears as new |
| JS-072 | Optional write-back of surfaced roles to a separate tab | P2 | S | Never touches the main tracker tab |

## E8: Digest

| ID | Story | Pri | Size | Acceptance criteria |
|---|---|---|---|---|
| JS-080 | HTML digest template: top roles with score, rationale, gaps, warm contacts, apply link | P0 | M | Reads well on phone and desktop |
| JS-081 | Send via Gmail API or SMTP | P0 | S | Arrives by 7:00 AM CT |
| JS-082 | "Nothing worth your time today" version | P0 | S | Short email, not silence, so a broken run is noticeable |
| JS-083 | Run health footer: sources checked, failures, cost | P1 | S | Failures visible without reading logs |
| JS-084 | Local HTML report archive by date | P2 | S | `jobscout digest --open` shows any past day |

## E9: Scheduling and ops

| ID | Story | Pri | Size | Acceptance criteria |
|---|---|---|---|---|
| JS-090 | `launchd` job on pickles-data-center for a daily 5:30 AM CT run | P0 | S | Runs with the main laptop closed or traveling |
| JS-091 | Failure alerting: if the run errors or doesn't finish, send a short alert email | P1 | S | A dead pipeline gets noticed within a day |
| JS-092 | Secrets handling on the always-on Mac (keychain or locked-down `.env`) | P0 | S | No keys in the repo or shell history |
| JS-093 | GitHub Actions scheduled run as a backup runner | P2 | M | Works with secrets in repo settings, personal files injected at runtime |

## E10: Showcase

| ID | Story | Pri | Size | Acceptance criteria |
|---|---|---|---|---|
| JS-100 | Sanitized sample data + `jobscout demo` that runs end to end with no keys | P1 | M | Anyone can clone and see a digest in 2 minutes |
| JS-101 | README polish: problem, architecture diagram, screenshots of a digest | P1 | S | Reads well to a hiring manager in 60 seconds |
| JS-102 | Write-up of the scoring eval results (what the scorer gets right and wrong) | P1 | S | Honest numbers, including misses |
| JS-103 | Small read-only dashboard of the pipeline (roles over time, by segment, by tier, sources) | P2 | M | Built from the SQLite store |
| JS-104 | Short demo talk track for interviews (problem, design choices, what you'd do next) | P2 | S | Fits in 3 minutes |

## E11: Later

| ID | Story | Pri | Size | Notes |
|---|---|---|---|---|
| JS-110 | Pre-posting signals: funding rounds, new bank partnerships, new PS/implementation leader hires at watchlist companies | P2 | L | New leaders build teams before reqs post |
| JS-111 | Feedback loop: thumbs up/down links in the digest feed back into scoring thresholds and the eval set | P2 | M | Precision improves over time |
| JS-112 | Ghost detector: flag application threads with no reply after N days and draft a nudge | P2 | M | Drafts only, never sends |
| JS-113 | Watchlist expansion: suggest new companies similar to the ones that score well | P2 | M | Human approves every addition |
| JS-114 | Handoff to resume tailoring: export a role's JD + gap flags in a format ready for the resume tool | P2 | S | One click from digest |

---

## Open decisions

- **Product name.** JobScout is a placeholder.
- **Repo visibility.** Public from day one with personal data gitignored, or private until M4.
- **Comp floor.** Set the number in `filters.yaml`.
- **Digest delivery.** Gmail API (already connected) vs. plain SMTP.
- **Watchlist in repo?** Committing the company list is low risk; the status/history columns probably shouldn't be public.
