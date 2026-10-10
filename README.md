# JobScout

*Working title. Rename freely.*

A personal job-search radar. Every morning it checks the careers boards of a curated list of target companies, pulls in job-alert emails, throws out the noise, scores what's left against a real candidate profile with Claude, flags who you know at each company, and sends a short digest of the roles actually worth acting on.

Built by Matt Reigh as a working tool for his own search and as a showcase of applied AI in a practical workflow.

---

## The problem

Job boards are a firehose. A senior candidate in a niche lane (fintech implementation, delivery, and platform roles) ends up:

- Checking dozens of company career pages by hand, and still finding roles days late
- Reading 30 job descriptions to find the 3 that fit
- Re-reading roles already applied to or already passed on
- Applying cold when a warm path existed and nobody noticed

The data also says something important: in this search, warm channels (inside champions, known recruiters) produced nearly all the real interview traction, while cold applications mostly went nowhere. **So the goal is not more roles. It's fewer, better roles, found early, with the warm path attached.**

## Goals

1. **Find roles early.** Surface new postings at target companies within 24 hours, usually before they hit the big aggregators.
2. **Filter hard.** Apply non-negotiable rules (location, comp floor, role type) before anything reaches a human.
3. **Score honestly.** Rank each role against the candidate's verified background with an explanation and explicit gap flags. No inflated fit scores.
4. **Attach the warm path.** For every surfaced role, show first-degree connections at that company.
5. **Never resurface the dead.** Dedupe against the application tracker and past decisions.
6. **Take under 10 minutes a day** to triage.

## Non-goals

- Auto-applying to anything. A human decides and applies.
- Scraping LinkedIn, Indeed, or any site that prohibits it, or automating logins.
- Generating resumes or cover letters (a possible later handoff, not part of this product).
- Being a general-purpose job board for other people (though the design keeps personal data separable, so it could be).

---

## How it works

```
 Watchlist (companies, tiers, ATS)          Job-alert emails (Gmail)
            │                                        │
            ▼                                        ▼
   ┌──────────────────┐                   ┌──────────────────┐
   │  ATS collectors  │                   │  Alert parsers   │
   │ Greenhouse, Lever│                   │ LinkedIn, Indeed │
   │ Ashby, Workday...│                   │                  │
   └────────┬─────────┘                   └────────┬─────────┘
            └──────────────────┬───────────────────┘
                               ▼
                    ┌─────────────────────┐
                    │ Normalize + dedupe  │  one canonical record per job
                    └──────────┬──────────┘
                               ▼
                    ┌─────────────────────┐
                    │ Hard filters (rules)│  location, comp floor, title, exclusions
                    └──────────┬──────────┘
                               ▼
                    ┌─────────────────────┐
                    │ Fit scoring (Claude)│  score + rationale + gap flags
                    └──────────┬──────────┘
                               ▼
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
   Warm-path match      Tracker check         SQLite history
   (LinkedIn export)    (Google Sheet)        (seen, scored, status)
          └────────────────────┼────────────────────┘
                               ▼
                    ┌─────────────────────┐
                    │   Morning digest    │  email + local HTML report
                    └─────────────────────┘
```

### 1. Watchlist
The seed list of target companies lives in `config/watchlist.csv` (exported from `Target_Company_Watchlist.xlsx`). Each row has a tier (A/B/C), segment, roles to watch, status/history, and ATS. Tier controls how aggressively roles get surfaced.

### 2. ATS detection
For companies marked `Auto-detect`, the tool probes the public job-board endpoints of common applicant tracking systems and records which one answers. Run once on setup, then re-checked weekly so moves between ATS vendors get caught.

### 3. Collectors
One small collector per source, all returning the same normalized shape.

| Source | Method | Notes |
|---|---|---|
| Greenhouse | Public job board API (`boards-api.greenhouse.io/v1/boards/{token}/jobs`) | JSON, includes full descriptions |
| Lever | Public postings API (`api.lever.co/v0/postings/{company}?mode=json`) | JSON |
| Ashby | Public posting API (`api.ashbyhq.com/posting-api/job-board/{name}`) | JSON, often includes comp |
| SmartRecruiters | Public postings API | JSON |
| Workable | Public jobs endpoint | Verify endpoint during build |
| Workday | Careers site JSON search endpoint | Per-tenant URL; most fiddly collector |
| iCIMS, Rippling, custom pages | HTML fetch + LLM extraction fallback | Last resort, rate limited |
| LinkedIn / Indeed | Parse saved-search alert emails via Gmail API | No direct scraping |
| Staffing boards (Kforce, Apex, etc.) | Filtered public search pages | Local + remote FS only |

### 4. Normalize and dedupe
Every posting becomes one canonical `Job` record with a stable fingerprint (company + normalized title + location + requisition ID when available). The same role seen on Greenhouse and in a LinkedIn alert collapses into one record. Postings that disappear from a board get marked closed.

### 5. Hard filters
Cheap, deterministic rules run before any AI call:

- Location: remote (US) or hybrid within reach of Milwaukee (MKE, Madison, Chicago)
- Comp: below the configured floor gets dropped when comp is listed
- Title/level: include and exclude keyword lists
- Exclusions: relocation required, heavy onsite outside the region, hands-on full-stack development bar, P&L ownership as a core requirement

### 6. Fit scoring
Survivors get scored by Claude against `profile/candidate.yaml`, which holds the verified career history, target lanes, and dealbreakers. Each scored job returns:

- **Fit score** (0 to 100) and a **recommendation**: Apply, Network first, Watch, Skip
- **Why it fits**: two or three concrete matches to real experience
- **Gap flags**: the honest gaps a hiring manager would spot
- **Level read**: IC vs. leader, and whether the title undersells or oversells the role

Scoring is cached by job fingerprint and description hash, so a role is only scored once unless its description changes.

### 7. Warm paths
A one-time import of the LinkedIn connections export (`Connections.csv`, downloaded from LinkedIn settings) gets matched to watchlist companies with fuzzy name matching. Every digest entry shows who you know there. No LinkedIn scraping involved.

### 8. Tracker sync
Reads the existing Google Sheet application tracker so roles already applied to, rejected, or passed on are suppressed. Optional write-back adds a "Surfaced by JobScout" tab.

### 9. Digest
One email each morning, plus a local HTML report:

- Top 5 to 10 new roles, ranked, with score, rationale, gap flags, warm contacts, and the direct apply link
- A short "also new, lower fit" list
- Closed or changed postings at A-tier companies
- Run health: sources checked, failures, cost

---

## Design principles

- **Polite and legal by default.** Public APIs and public pages only, respectful rate limits, honest user agent, no login automation, no prohibited sites.
- **Rules before AI.** Deterministic filters do the cheap work; Claude only sees roles that already passed them. Keeps cost low and behavior predictable.
- **Honest scoring.** The scorer is told to find gaps, not to sell. Fit scores should hold up in an actual interview.
- **Personal data stays out of the repo.** Profile, connections, tracker IDs, and API keys live in gitignored files. The repo ships with sanitized sample data and a demo mode.
- **Everything is replayable.** Raw source payloads are stored, so filters and scoring can be re-run and tuned without re-fetching.

---

## Tech stack

| Concern | Choice |
|---|---|
| Language | Python 3.12 |
| HTTP | `httpx` with retries and per-host rate limits |
| Storage | SQLite (single file, zero ops) |
| Models / validation | `pydantic` |
| AI scoring + extraction | Claude via the Anthropic Python SDK |
| Email in | Gmail API (read-only scope, alert labels only) |
| Email out | Gmail API send or SMTP |
| Tracker | Google Sheets API |
| CLI | `typer` |
| Scheduling | `launchd` on the always-on Mac (pickles-data-center), with GitHub Actions as an alternative |
| Tests / CI | `pytest`, recorded fixtures per collector, GitHub Actions |

## Repo layout (planned)

```
jobscout/
  collectors/        # one module per source (greenhouse.py, lever.py, ...)
  detect/            # ATS detection
  pipeline/          # normalize, dedupe, filter, score, warm paths
  digest/            # email + HTML rendering
  store/             # SQLite schema and queries
  cli.py
config/
  watchlist.csv      # target companies (safe to commit, or gitignore if preferred)
  filters.yaml       # hard filter rules
profile/             # gitignored: candidate.yaml, Connections.csv
samples/             # sanitized demo data
tests/
  fixtures/          # recorded API responses
docs/
  BACKLOG.md
```

## CLI (planned)

```bash
jobscout detect            # find each company's ATS
jobscout collect           # pull postings from all sources
jobscout run               # full pipeline: collect, filter, score, digest
jobscout run --dry-run     # everything except sending the email
jobscout digest --open     # render today's report locally
jobscout demo              # run end to end on sample data, no keys needed
```

---

## Success metrics

| Metric | Target |
|---|---|
| A-tier roles surfaced within 24h of posting | 90%+ |
| Daily triage time | Under 10 minutes |
| Top-5 precision (roles marked worth acting on) | 60%+ after tuning |
| Roles surfaced with at least one warm contact | Tracked, trending up |
| Dead or duplicate roles in the digest | Zero |
| Daily run cost (AI calls) | Under $1 |

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # add keys later; nothing needs one yet
jobscout init               # folders, starter config, database
jobscout doctor             # checks config, database, keys
pytest                      # runs offline, no network
```

### Watchlist and job-board detection

Your target companies live in a spreadsheet at `profile/watchlist.xlsx` (gitignored).
No list of your own yet? Try the scrubbed demo list in `samples/watchlist.sample.csv`.

```bash
jobscout watchlist import                 # or: --file samples/watchlist.sample.csv
jobscout detect                           # finds each company's job board
jobscout watchlist show --unresolved      # what needs a Board URL or a second look
```

Detection guesses board names from the company name and checks the public job-board
APIs of Greenhouse, Lever, Ashby, SmartRecruiters, and Workable. Each hit gets a
confidence: **confirmed** (the board's own name matches), **likely** (strong match, but
the ATS doesn't report a name), or **review** (could be a different company).

When it can't find a board (Workday, iCIMS, custom career sites), paste the careers page
URL into the **Board URL (override)** column, re-import, and re-run `detect`. Overrides
always win. Re-running `detect` only re-checks new, failed, or week-old results; use
`--refresh` to re-check everything or `--company "Q2"` for one company.

A weekly GitHub Action (`Live API check`) runs detection for real against the sample list,
so API changes on the job boards' side get caught.

## Status

- **E0 Foundation: done.** Package, typed config, versioned SQLite schema, CLI, structured logging, run tracking, offline test harness, CI.
- **E1 Watchlist + ATS detection: done.** Spreadsheet import, slug guessing, five ATS probers, confidence scoring, Workday and other overrides, ATS change history, polite rate-limited HTTP with retries, weekly live API check.

**Next:** E2, collectors that pull the actual postings. See [BACKLOG.md](docs/BACKLOG.md).
