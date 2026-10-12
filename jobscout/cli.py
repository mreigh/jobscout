"""JobScout command line.

    jobscout init       set up local folders, starter config, and the database
    jobscout doctor     check config, database, and keys
    jobscout watchlist  import / show target companies
    jobscout detect     find each company's ATS
    jobscout collect    pull postings from all sources     (E2)
    jobscout run        full pipeline                       (E2-E8)
    jobscout digest     render the morning digest           (E8)
    jobscout runs       show recent run history
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import typer

from jobscout import __version__
from jobscout.config import ConfigError, Settings, load_filters, load_settings
from jobscout.logging_setup import setup_logging
from jobscout.runs import recent_runs, tracked_run
from jobscout.store import connect, current_version
from jobscout.watchlist import import_watchlist, load_watchlist

app = typer.Typer(
    help="JobScout: watch target companies, filter hard, score honestly, attach the warm path.",
    no_args_is_help=True,
    add_completion=False,
)
log = logging.getLogger("jobscout.cli")

watchlist_app = typer.Typer(help="Import and inspect the target company watchlist.",
                            no_args_is_help=True)
app.add_typer(watchlist_app, name="watchlist")


@dataclass
class Ctx:
    settings: Settings


def _fail(msg: str, code: int = 2) -> None:
    typer.secho(msg, fg=typer.colors.RED, err=True)
    raise typer.Exit(code)


@app.callback()
def main(
    ctx: typer.Context,
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging."),
) -> None:
    try:
        settings = load_settings()
    except ConfigError as e:
        _fail(str(e))
    setup_logging("DEBUG" if verbose else settings.log_level, settings.log_dir)
    ctx.obj = Ctx(settings=settings)


@app.command()
def version() -> None:
    """Print the version."""
    typer.echo(f"jobscout {__version__}")


@app.command()
def init(ctx: typer.Context) -> None:
    """Create local folders, a starter filters.yaml if missing, and the database."""
    s: Settings = ctx.obj.settings
    s.config_dir.mkdir(parents=True, exist_ok=True)
    if not s.filters_path.exists():
        template = resources.files("jobscout") / "templates" / "filters.yaml"
        with resources.as_file(template) as src:
            shutil.copy(src, s.filters_path)
        typer.echo(f"Created starter config: {s.filters_path}")
    else:
        typer.echo(f"Config already present: {s.filters_path}")
    conn = connect(s.db_path)
    typer.echo(f"Database ready: {s.db_path} (schema v{current_version(conn)})")
    conn.close()


@app.command()
def doctor(ctx: typer.Context) -> None:
    """Check that config, database, and keys are in order."""
    s: Settings = ctx.obj.settings
    ok = True

    try:
        f = load_filters(s.filters_path)
        typer.echo(f"[ok]   filters.yaml loaded (comp floor ${f.comp.floor_usd:,})")
    except ConfigError as e:
        ok = False
        typer.secho(f"[fail] {e}", fg=typer.colors.RED)

    try:
        conn = connect(s.db_path)
        typer.echo(f"[ok]   database {s.db_path} at schema v{current_version(conn)}")
        conn.close()
    except Exception as e:  # noqa: BLE001
        ok = False
        typer.secho(f"[fail] database: {e}", fg=typer.colors.RED)

    if s.anthropic_api_key:
        typer.echo("[ok]   ANTHROPIC_API_KEY set")
    else:
        typer.secho("[warn] ANTHROPIC_API_KEY not set (needed for scoring in E5)", fg="yellow")

    raise typer.Exit(0 if ok else 1)


def _stub(ctx: typer.Context, command: str, ships_in: str) -> None:
    """Shared body for commands that exist but aren't built yet."""
    s: Settings = ctx.obj.settings
    try:
        load_filters(s.filters_path)
    except ConfigError as e:
        _fail(str(e))
    conn = connect(s.db_path)
    with tracked_run(conn, command):
        typer.echo(f"`{command}` is wired up but not built yet (ships in {ships_in}).")
    conn.close()


@watchlist_app.command("import")
def watchlist_import(
    ctx: typer.Context,
    file: Path = typer.Option(None, "--file", "-f", help="Spreadsheet to import (.xlsx or .csv)."),
) -> None:
    """Load the watchlist spreadsheet into the database (safe to re-run)."""
    s: Settings = ctx.obj.settings
    path = file or s.watchlist_path
    try:
        entries = load_watchlist(path)
    except ConfigError as e:
        _fail(str(e))
    conn = connect(s.db_path)
    with tracked_run(conn, "watchlist import") as run:
        res = import_watchlist(conn, entries)
        run.incr("companies", len(entries))
        run.incr("added", len(res.added))
        run.incr("updated", len(res.updated))
        run.incr("deactivated", len(res.deactivated))
    conn.close()
    typer.echo(f"Imported {len(entries)} companies from {path}")
    typer.echo(f"  added {len(res.added)}, updated {len(res.updated)}, "
               f"unchanged {res.unchanged}, removed {len(res.deactivated)}")
    for name in res.deactivated:
        typer.echo(f"  - no longer on watchlist: {name}")
    for name in res.override_changed:
        typer.echo(f"  ~ board URL changed, will re-detect: {name}")


@watchlist_app.command("show")
def watchlist_show(
    ctx: typer.Context,
    tier: str = typer.Option(None, "--tier", "-t", help="Only this tier (A, B, or C)."),
    unresolved: bool = typer.Option(
        False, "--unresolved", "-u", help="Only companies that need a board URL or a look."
    ),
) -> None:
    """List watchlist companies and where their jobs are posted."""
    conn = connect(ctx.obj.settings.db_path)
    sql = "SELECT * FROM companies WHERE active = 1"
    params: list = []
    if tier:
        sql += " AND tier = ?"
        params.append(tier.upper())
    if unresolved:
        sql += (" AND (detect_status IS NULL OR detect_status IN ('not_found','needs_url','error')"
                " OR detect_confidence = 'review')")
    rows = conn.execute(sql + " ORDER BY tier, name", params).fetchall()
    conn.close()
    if not rows:
        typer.echo("Nothing to show. Run `jobscout watchlist import` first?")
        return
    for r in rows:
        where = f"{r['ats']}/{r['ats_token']}" if r["ats"] and r["ats_token"] else (r["ats"] or "-")
        status = r["detect_status"] or "not checked"
        if r["detect_confidence"] and r["detect_status"] in ("found", "override"):
            status += f" ({r['detect_confidence']})"
        jobs = f"{r['job_count']} jobs" if r["job_count"] is not None else ""
        typer.echo(f"{r['tier']}  {r['name'][:32]:<32} {status:<22} {where[:40]:<40} {jobs}")
        if unresolved and r["detect_detail"]:
            msg = json.loads(r["detect_detail"]).get("message", "")
            if msg:
                typer.echo(f"     {msg}")
    typer.echo(f"\n{len(rows)} companies")


_STATUS_MARK = {"found": "+", "override": "+", "not_found": "?", "needs_url": "!", "error": "x"}


@app.command()
def detect(
    ctx: typer.Context,
    company: list[str] = typer.Option(
        None, "--company", "-c", help="Only this company (repeatable)."
    ),
    refresh: bool = typer.Option(False, "--refresh", help="Re-check every company."),
    stale_days: int = typer.Option(7, help="Re-check companies last checked this many days ago."),
    workers: int = typer.Option(6, help="Companies checked in parallel."),
) -> None:
    """Find each watchlist company's applicant tracking system (job board)."""
    from jobscout.detect import run_detection
    from jobscout.detect.detector import companies_to_detect
    from jobscout.http import PoliteClient

    s: Settings = ctx.obj.settings
    conn = connect(s.db_path)
    if conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0] == 0:
        conn.close()
        _fail("No companies yet. Run `jobscout watchlist import` first.")
    rows = companies_to_detect(conn, refresh=refresh, stale_days=stale_days, names=company)
    if not rows:
        typer.echo("Everything is up to date. Use --refresh to re-check all companies.")
        conn.close()
        return

    typer.echo(f"Checking {len(rows)} companies...")

    def show(r):
        where = f"{r.ats}/{r.token}" if r.token else ""
        conf = f" [{r.confidence}]" if r.confidence else ""
        typer.echo(f"  {_STATUS_MARK.get(r.status, ' ')} {r.company[:32]:<32} {where}{conf}")

    with tracked_run(conn, "detect") as run, PoliteClient() as http:
        results = run_detection(conn, http, rows, workers=workers, on_result=show)
        for r in results:
            run.incr(r.status)
            if r.confidence == "review":
                run.incr("review")
    conn.close()

    counts = run.counts
    typer.echo(
        f"\nFound {counts['found'] + counts['override']}, needs URL {counts['needs_url']}, "
        f"not found {counts['not_found']}, errors {counts['error']}, to review {counts['review']}"
    )
    if counts["needs_url"] + counts["not_found"] + counts["review"] + counts["error"]:
        typer.echo("See what needs attention: jobscout watchlist show --unresolved")


@app.command()
def collect(
    ctx: typer.Context,
    company: list[str] = typer.Option(
        None, "--company", "-c", help="Only this company (repeatable)."
    ),
    tier: list[str] = typer.Option(None, "--tier", "-t", help="Only this tier (repeatable)."),
    workers: int = typer.Option(6, help="Companies fetched in parallel."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Summary only."),
) -> None:
    """Pull open postings from every company's job board and track what's new or closed."""
    from jobscout.collect.runner import companies_to_collect, run_collection
    from jobscout.gates import apply_gates
    from jobscout.http import PoliteClient

    s: Settings = ctx.obj.settings
    try:
        filters = load_filters(s.filters_path)
    except ConfigError as e:
        _fail(str(e))
    conn = connect(s.db_path)
    rows = companies_to_collect(conn, names=company, tiers=tier)
    if not rows:
        conn.close()
        _fail("No matching companies. Run `jobscout watchlist import` and `jobscout detect` first.")

    def show(r):
        if quiet:
            return
        if r.status == "ok":
            sv = r.saved
            extra = []
            if sv.new:
                extra.append(f"{len(sv.new)} new")
            if sv.updated:
                extra.append(f"{len(sv.updated)} updated")
            if sv.closed:
                extra.append(f"{len(sv.closed)} closed")
            if sv.reopened:
                extra.append(f"{len(sv.reopened)} reopened")
            tail = f" ({', '.join(extra)})" if extra else ""
            typer.echo(f"  + {r.tier} {r.company[:32]:<32} {sv.open_count:>4} open{tail}")
        elif r.status == "error":
            typer.echo(f"  x {r.tier} {r.company[:32]:<32} {r.error}")

    typer.echo(f"Collecting from {len(rows)} companies...")
    with tracked_run(conn, "collect") as run, PoliteClient() as http:
        results = run_collection(conn, http, rows, run_id=run.id, workers=workers, on_result=show)
        for r in results:
            run.incr(r.status)
            if r.saved:
                run.incr("open", r.saved.open_count)
                run.incr("new", len(r.saved.new))
                run.incr("closed", len(r.saved.closed))
        verdicts = apply_gates(conn, filters)
        run.incr("gate_pass", verdicts.get("pass", 0))
        run.incr("gate_out", sum(n for v, n in verdicts.items() if v != "pass"))
    conn.close()

    c = run.counts
    typer.echo(
        f"\n{c['ok']} boards read, {c['open']} open postings, {c['new']} new, {c['closed']} closed"
        f" | {c['error']} errors, {c['unsupported']} not readable yet, {c['review']} need review"
    )
    top = ", ".join(f"{v} {n}" for v, n in sorted(
        ((v, n) for v, n in verdicts.items() if v != "pass"), key=lambda x: -x[1])[:4])
    typer.echo(f"Gates: {c['gate_pass']} pass, {c['gate_out']} filtered out"
               + (f" (top: {top})" if top else ""))
    if c["new"]:
        typer.echo("See what passed: jobscout jobs --new   (everything: --all)")


def _job_filters():
    """Options shared by `jobs` and `export`."""
    return dict(
        new=typer.Option(False, "--new", "-n", help="Only first seen in the latest collect."),
        days=typer.Option(None, "--days", "-d", help="Only first seen in the last N days."),
        match=typer.Option(False, "--match", "-m",
                           help="Rough title filter using filters.yaml keywords (E5 replaces it)."),
        remote=typer.Option(False, "--remote", help="Only postings marked remote."),
        company=typer.Option(None, "--company", "-c", help="Only this company (repeatable)."),
        tier=typer.Option(None, "--tier", "-t", help="Only this tier (repeatable)."),
        search=typer.Option(None, "--search", "-s", help="Title contains this text."),
        closed=typer.Option(False, "--closed", help="Recently closed postings instead of open."),
        show_all=typer.Option(False, "--all", "-a",
                              help="Include postings the hard gates filtered out."),
    )


_F = _job_filters()


def _query_jobs(s: Settings, new, days, match, remote, company, tier, search, closed,
                show_all=False):
    """Rows for the given filters, plus the set of job ids that are new since the last collect."""
    from jobscout.export import title_matches

    conn = connect(s.db_path)
    last = conn.execute(
        "SELECT started_at FROM runs WHERE command = 'collect' AND status = 'success'"
        " ORDER BY id DESC LIMIT 1"
    ).fetchone()
    sql = ("SELECT j.*, c.name AS company, c.tier, c.segment FROM jobs j"
           " JOIN companies c ON c.id = j.company_id WHERE c.active = 1")
    params: list = []
    sql += " AND j.closed_at IS NOT NULL" if closed else " AND j.closed_at IS NULL"
    if not show_all and not closed:
        sql += " AND j.filter_result = 'pass'"
    if new and last:
        sql += " AND j.first_seen_at >= datetime(?)"
        params.append(last["started_at"])
    if days:
        sql += " AND j.first_seen_at >= datetime('now', ?)"
        params.append(f"-{days} days")
    if remote:
        sql += " AND j.remote = 1"
    if company:
        sql += f" AND lower(c.name) IN ({', '.join('?' * len(company))})"
        params += [x.lower() for x in company]
    if tier:
        sql += f" AND c.tier IN ({', '.join('?' * len(tier))})"
        params += [t.upper() for t in tier]
    if search:
        sql += " AND lower(j.title) LIKE ?"
        params.append(f"%{search.lower()}%")
    rows = conn.execute(sql + " ORDER BY c.tier, j.first_seen_at DESC, c.name", params).fetchall()
    new_ids = set()
    if last:
        new_ids = {r[0] for r in conn.execute(
            "SELECT id FROM jobs WHERE first_seen_at >= datetime(?)", (last["started_at"],))}
    conn.close()

    filters = None
    try:
        filters = load_filters(s.filters_path)
    except ConfigError as e:
        if match:
            _fail(str(e))
    if match:
        rows = [r for r in rows if title_matches(r["title"], filters)]

    # Collapse identical postings (same company, title, location): big Workday
    # tenants post one req per seat, e.g. five "Account Manager II, Client Success"
    # rows at FIS Milwaukee. The survivor carries dup_count.
    merged, seen = [], {}
    for r in rows:
        key = (r["company"], r["title"], r["location"], r["remote"])
        if key in seen:
            seen[key]["dup_count"] += 1
            continue
        d = dict(r)
        d["dup_count"] = 1
        seen[key] = d
        merged.append(d)
    return merged, new_ids, filters


@app.command("jobs")
def jobs_cmd(
    ctx: typer.Context,
    new: bool = _F["new"], days: int = _F["days"], match: bool = _F["match"],
    remote: bool = _F["remote"], company: list[str] = _F["company"], tier: list[str] = _F["tier"],
    search: str = _F["search"], closed: bool = _F["closed"], show_all: bool = _F["show_all"],
    limit: int = typer.Option(50, "--limit", "-l"),
) -> None:
    """List collected job postings in the terminal (gated to 'pass' unless --all)."""
    rows, _, _ = _query_jobs(ctx.obj.settings, new, days, match, remote, company, tier, search,
                             closed, show_all=show_all)
    if not rows:
        typer.echo("No postings match.")
        return
    for r in rows[:limit]:
        where = "Remote" if r["remote"] == 1 else (r["location"] or "")
        pay = ""
        if r["comp_min"]:
            pay = f"${r['comp_min'] // 1000}k-${(r['comp_max'] or r['comp_min']) // 1000}k"
        title = r["title"] + (f" (x{r['dup_count']} reqs)" if r["dup_count"] > 1 else "")
        typer.echo(f"{r['tier']}  {r['company'][:22]:<22} {title[:58]:<58} "
                   f"{where[:24]:<24} {pay:<11} {r['url'] or ''}")
    more = f" (showing {limit}; use --limit or `jobscout export`)" if len(rows) > limit else ""
    typer.echo(f"\n{len(rows)} postings{more}")


@app.command()
def export(
    ctx: typer.Context,
    new: bool = _F["new"], days: int = _F["days"], match: bool = _F["match"],
    remote: bool = _F["remote"], company: list[str] = _F["company"], tier: list[str] = _F["tier"],
    search: str = _F["search"], closed: bool = _F["closed"], show_all: bool = _F["show_all"],
    out: Path = typer.Option(None, "--out", "-o", help="Where to write (default reports/)."),
    open_file: bool = typer.Option(True, "--open/--no-open", help="Open it when done (macOS)."),
) -> None:
    """Write postings to an Excel file you can sort and filter. Same filters as `jobs`."""
    import subprocess
    import sys
    from datetime import date

    from jobscout.export import write_jobs_xlsx

    s: Settings = ctx.obj.settings
    rows, new_ids, filters = _query_jobs(s, new, days, match, remote, company, tier, search,
                                         closed, show_all=show_all)
    if not rows:
        typer.echo("No postings match.")
        return
    path = out or Path("reports") / f"jobs-{date.today().isoformat()}.xlsx"
    write_jobs_xlsx(rows, path, new_ids, filters)
    typer.echo(f"Wrote {len(rows)} postings to {path}")
    if open_file and sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)


@app.command()
def regate(ctx: typer.Context) -> None:
    """Re-apply the hard gates to every open posting (run after editing filters.yaml)."""
    from jobscout.gates import apply_gates

    s: Settings = ctx.obj.settings
    try:
        filters = load_filters(s.filters_path)
    except ConfigError as e:
        _fail(str(e))
    conn = connect(s.db_path)
    with tracked_run(conn, "regate") as run:
        verdicts = apply_gates(conn, filters)
        run.incr("pass", verdicts.get("pass", 0))
        run.incr("filtered", sum(n for v, n in verdicts.items() if v != "pass"))
    conn.close()
    typer.echo(f"{verdicts.get('pass', 0)} pass, "
               f"{sum(n for v, n in verdicts.items() if v != 'pass')} filtered out:")
    for v, n in sorted(verdicts.items(), key=lambda x: -x[1]):
        if v != "pass":
            typer.echo(f"  {n:>5}  {v}")


@app.command()
def run(
    ctx: typer.Context,
    dry_run: bool = typer.Option(False, "--dry-run", help="Do everything except send email."),
) -> None:
    """Full pipeline: collect, filter, score, digest."""
    _stub(ctx, "run --dry-run" if dry_run else "run", "M2")


@app.command()
def digest(ctx: typer.Context) -> None:
    """Render the morning digest."""
    _stub(ctx, "digest", "E8")


@app.command()
def runs(
    ctx: typer.Context,
    limit: int = typer.Option(10, "--limit", "-n", help="How many runs to show."),
) -> None:
    """Show recent run history."""
    conn = connect(ctx.obj.settings.db_path)
    rows = recent_runs(conn, limit)
    conn.close()
    if not rows:
        typer.echo("No runs yet.")
        return
    for r in rows:
        counts = json.loads(r["counts_json"])
        counts_str = " ".join(f"{k}={v}" for k, v in counts.items()) or "-"
        line = f"#{r['id']:<4} {r['started_at']}  {r['command']:<14} {r['status']:<8} {counts_str}"
        if r["error"]:
            line += f"  error: {r['error']}"
        typer.echo(line)


if __name__ == "__main__":
    app()
