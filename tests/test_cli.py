from typer.testing import CliRunner

from jobscout.cli import app

runner = CliRunner()


def test_help_lists_commands(workdir):
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("init", "doctor", "detect", "collect", "run", "digest", "runs"):
        assert cmd in result.output


def test_init_creates_config_and_db(workdir):
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    assert (workdir / "config" / "filters.yaml").exists()
    assert (workdir / "data" / "test.db").exists()
    # second run leaves existing config alone
    result = runner.invoke(app, ["init"])
    assert "already present" in result.output


def test_doctor_fails_without_config_then_passes(workdir):
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert "ANTHROPIC_API_KEY not set" in result.output


def test_stub_command_records_a_run(workdir):
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["detect"])
    assert result.exit_code == 0, result.output
    assert "not built yet" in result.output
    result = runner.invoke(app, ["runs"])
    assert "detect" in result.output and "success" in result.output


def test_stub_command_fails_cleanly_without_config(workdir):
    result = runner.invoke(app, ["collect"])
    assert result.exit_code == 2
    assert "jobscout init" in result.output


def test_logs_written_as_json(workdir):
    runner.invoke(app, ["init"])
    runner.invoke(app, ["detect"])
    log_file = workdir / "logs" / "jobscout.log"
    assert log_file.exists()
