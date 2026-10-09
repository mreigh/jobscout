"""JobScout command line.

    jobscout init       set up local folders, starter config, and the database
    jobscout doctor     check config, database, and keys
    jobscout detect     find each company's ATS            (E1)
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

import typer

from jobscout import __version__
from jobscout.config import ConfigError, Settings, load_filters, load_settings
from jobscout.logging_setup import setup_logging
from jobscout.runs import recent_runs, tracked_run
from jobscout.store import connect, current_version

app = typer.Typer(
    help="JobScout: watch target companies, filter hard, score honestly, attach the warm path.",
    no_args_is_help=True,
    add_completion=False,
)
log = logging.getLogger("jobscout.cli")


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


@app.command()
def detect(ctx: typer.Context) -> None:
    """Find each watchlist company's applicant tracking system."""
    _stub(ctx, "detect", "E1 / JS-011")


@app.command()
def collect(ctx: typer.Context) -> None:
    """Pull postings from every source."""
    _stub(ctx, "collect", "E2")


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
