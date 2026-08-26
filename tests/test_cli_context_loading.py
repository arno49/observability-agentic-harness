"""Regression tests for oah.cli._load_context/ContextLoadError -- found by
adversarial review: 5 of the 6 --context-accepting commands (gaps, design,
event-schema, dtos, readiness) read and validated the file with zero error
handling, so a missing file or malformed YAML produced a raw traceback
instead of the clean 'error: ...' treatment every other input-validation
failure in this CLI already gets."""
import pytest

from oah.cli import _load_context, ContextLoadError


def test_missing_file_raises_clean_error(tmp_path):
    with pytest.raises(ContextLoadError, match="could not read"):
        _load_context(str(tmp_path / "does-not-exist.yaml"))


def test_malformed_yaml_raises_clean_error(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(": : : not valid yaml [")
    with pytest.raises(ContextLoadError, match="not valid YAML"):
        _load_context(str(path))


def test_yaml_that_does_not_match_context_schema_raises_clean_error(tmp_path):
    path = tmp_path / "wrong_shape.yaml"
    path.write_text("just_a_string: true\n")
    with pytest.raises(ContextLoadError, match="does not match context.schema.json"):
        _load_context(str(path))


def test_valid_context_yaml_loads_successfully(tmp_path):
    path = tmp_path / "context.yaml"
    path.write_text(
        "schema_version: '0.1.0'\n"
        "repo_git_sha: deadbeef\n"
        "interviewed_at: '2026-01-01T00:00:00Z'\n"
        "workflows:\n"
        "  - name: billing\n"
        "    criticality: critical\n"
    )
    context = _load_context(str(path))
    assert context["workflows"][0]["name"] == "billing"
