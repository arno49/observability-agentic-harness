"""oah/cli.py's _build_surface_map is the single dispatch point all six S1
call sites (map/gaps/design/event-schema/dtos/readiness) route through --
tested once here, directly, rather than duplicating this coverage six times
through each command's own heavier end-to-end test."""
import subprocess

from oah.cli import _build_surface_map


def _init_git_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.com", "-c", "user.name=t",
                     "commit", "--allow-empty", "-q", "-m", "init"], cwd=path, check=True)


def test_default_language_dispatches_to_python_adapter(tmp_path):
    (tmp_path / "app.py").write_text("import anthropic\nc = anthropic.Anthropic()\n"
                                      "c.messages.create(model='x')\n")
    _init_git_repo(tmp_path)

    surface_map, still_ambiguous = _build_surface_map(tmp_path, "deadbeef", "python")
    assert surface_map["repo"]["primary_language"] == "python"
    assert surface_map["coverage_stats"]["points_total"] == 1
    assert isinstance(still_ambiguous, list)


def test_typescript_language_dispatches_to_typescript_adapter(tmp_path):
    (tmp_path / "app.ts").write_text(
        'import Anthropic from "@anthropic-ai/sdk";\n'
        "const client = new Anthropic();\n"
        'client.messages.create({model: "x"});\n'
    )
    _init_git_repo(tmp_path)

    surface_map, still_ambiguous = _build_surface_map(tmp_path, "deadbeef", "typescript")
    assert surface_map["repo"]["primary_language"] == "typescript"
    assert surface_map["coverage_stats"]["points_total"] == 1
    assert still_ambiguous == []


def test_both_languages_return_the_same_2tuple_shape(tmp_path):
    """The real bug this dispatch layer depends on not having: before this
    fix, typescript_adapter.build_surface_map returned a bare dict, not a
    (surface_map, still_ambiguous) tuple like python_adapter's -- silently
    breaking every call site's `surface_map, still_ambiguous = ...` unpack
    the moment --language typescript was used."""
    (tmp_path / "app.py").write_text("x = 1\n")
    _init_git_repo(tmp_path)

    py_result = _build_surface_map(tmp_path, "deadbeef", "python")
    ts_result = _build_surface_map(tmp_path, "deadbeef", "typescript")
    assert len(py_result) == len(ts_result) == 2
    assert isinstance(py_result[1], list) and isinstance(ts_result[1], list)
