"""In-process test for cmd_backend_config's full flow -- fully
deterministic, no LLM/agent call anywhere, so nothing here needs
unittest.mock."""
import argparse
import subprocess

import yaml

from oah.cli import build_parser, cmd_backend_config


def _init_git_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.com", "-c", "user.name=t",
                     "commit", "--allow-empty", "-q", "-m", "init"], cwd=path, check=True)


def test_otel_only_writes_a_valid_config_to_stdout(tmp_path, capsys):
    target = tmp_path / "target_repo"
    target.mkdir()
    _init_git_repo(target)

    args = argparse.Namespace(target=str(target), backend="otel-only", output_dir=None)
    rc = cmd_backend_config(args)
    assert rc == 0
    out = capsys.readouterr().out
    parsed = yaml.safe_load(out)
    assert "debug" in parsed["exporters"]


def test_langfuse_writes_config_to_a_file(tmp_path):
    target = tmp_path / "target_repo"
    target.mkdir()
    _init_git_repo(target)
    output_dir = tmp_path / "out"

    args = argparse.Namespace(target=str(target), backend="langfuse", output_dir=str(output_dir))
    rc = cmd_backend_config(args)
    assert rc == 0

    config_path = output_dir / "otel-collector-config.yaml"
    assert config_path.is_file()
    parsed = yaml.safe_load(config_path.read_text())
    assert "otlphttp/langfuse" in parsed["exporters"]


def test_langfuse_prints_compose_note_to_stderr(tmp_path, capsys):
    target = tmp_path / "target_repo"
    target.mkdir()
    _init_git_repo(target)

    args = argparse.Namespace(target=str(target), backend="langfuse", output_dir=None)
    cmd_backend_config(args)
    err = capsys.readouterr().err
    assert "langfuse-web" in err
    assert "github.com/langfuse/langfuse" in err


def test_otel_only_has_no_compose_note_in_stderr(tmp_path, capsys):
    target = tmp_path / "target_repo"
    target.mkdir()
    _init_git_repo(target)

    args = argparse.Namespace(target=str(target), backend="otel-only", output_dir=None)
    cmd_backend_config(args)
    err = capsys.readouterr().err
    assert "docker-compose" not in err.lower() or "compose stack" not in err


def test_not_a_git_repo_returns_clean_error(tmp_path):
    target = tmp_path / "not_a_repo"
    target.mkdir()
    args = argparse.Namespace(target=str(target), backend="otel-only", output_dir=None)
    rc = cmd_backend_config(args)
    assert rc == 1


def test_invalid_backend_rejected_by_argparse_before_cmd_ever_runs():
    parser = build_parser()
    try:
        parser.parse_args(["backend-config", ".", "--backend", "datadog"])
        assert False, "argparse should have rejected an unsupported --backend choice"
    except SystemExit as e:
        assert e.code == 2  # argparse's own usage-error exit code
