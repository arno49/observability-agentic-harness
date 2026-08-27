"""CLI integration tests, run as real subprocesses through `oah` — the
resume test here is what actually caught state_db.create_run()'s UNIQUE
constraint bug (fixed, see test_state_db.py's idempotency test), so this
stays a real subprocess call rather than calling cmd_map() in-process,
which would have masked the same bug argparse/subprocess wiring could
reintroduce."""
import json
import subprocess
import sys
from pathlib import Path


def _run(args, cwd):
    return subprocess.run(
        [sys.executable, "-m", "oah.cli", *args],
        cwd=cwd, capture_output=True, text=True, timeout=30,
    )


def _init_git_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.com", "-c", "user.name=t",
                     "commit", "--allow-empty", "-q", "-m", "init"], cwd=path, check=True)


def test_doctor_exits_zero_on_healthy_environment(tmp_path):
    result = _run(["doctor"], cwd=tmp_path)
    assert result.returncode == 0
    assert "All checks passed" in result.stdout


def test_map_then_resume_is_idempotent(tmp_path):
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text("import anthropic\nc = anthropic.Anthropic()\n"
                                    "r = c.messages.create(model='x')\n")
    _init_git_repo(target)

    workdir = tmp_path / "workdir"
    workdir.mkdir()

    out1 = workdir / "sm1.json"
    first = _run(["map", str(target), "--run-id", "test-run", "-o", str(out1)], cwd=workdir)
    assert first.returncode == 0, first.stderr
    assert "already checkpointed" not in first.stderr

    out2 = workdir / "sm2.json"
    second = _run(["map", str(target), "--run-id", "test-run", "-o", str(out2)], cwd=workdir)
    assert second.returncode == 0, second.stderr
    assert "already checkpointed" in second.stderr

    assert json.loads(out1.read_text()) == json.loads(out2.read_text())

    manifest = json.loads((workdir / ".oah" / "runs" / "test-run.json").read_text())
    assert manifest["stages_completed"] == ["s1"]
    assert manifest["completed_at"] is not None
    assert manifest["started_at"] < manifest["completed_at"]


def test_map_rejects_non_git_target(tmp_path):
    target = tmp_path / "not_a_repo"
    target.mkdir()
    result = _run(["map", str(target)], cwd=tmp_path)
    assert result.returncode == 1
    assert "not a git repository" in result.stderr


def test_map_default_language_is_python(tmp_path):
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text("import anthropic\nc = anthropic.Anthropic()\n")
    _init_git_repo(target)

    workdir = tmp_path / "workdir"
    workdir.mkdir()
    result = _run(["map", str(target), "--run-id", "py-default-run"], cwd=workdir)
    assert result.returncode == 0, result.stderr

    manifest = json.loads((workdir / ".oah" / "runs" / "py-default-run.json").read_text())
    assert manifest["target"]["primary_language"] == "python"


def test_map_language_typescript_dispatches_to_ts_adapter(tmp_path):
    """E11-TS's own CLI dispatch: --language typescript must route `oah map`
    through oah/discovery/typescript_adapter.py, not silently no-op or fall
    back to the Python adapter (which would find zero points in a .ts-only
    target and mask a wiring bug as an empty-but-successful result)."""
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.ts").write_text(
        'import Anthropic from "@anthropic-ai/sdk";\n'
        "const client = new Anthropic();\n"
        'client.messages.create({model: "x"});\n'
    )
    _init_git_repo(target)

    workdir = tmp_path / "workdir"
    workdir.mkdir()
    out = workdir / "sm.json"
    result = _run(["map", str(target), "--language", "typescript",
                   "--run-id", "ts-run", "-o", str(out)], cwd=workdir)
    assert result.returncode == 0, result.stderr

    surface_map = json.loads(out.read_text())
    assert surface_map["repo"]["primary_language"] == "typescript"
    assert surface_map["coverage_stats"]["points_total"] == 1
    assert surface_map["points"][0]["kind"] == "llm_generation"

    manifest = json.loads((workdir / ".oah" / "runs" / "ts-run.json").read_text())
    assert manifest["target"]["primary_language"] == "typescript"
    # TS has no LLM-disambiguation counterpart yet (E11-TS's own stated scope
    # boundary) -- s1 must still reach "completed" since there's nothing left
    # ambiguous for it to wait on.
    assert manifest["stages_completed"] == ["s1"]


def test_map_language_java_dispatches_to_java_adapter(tmp_path):
    """E11-Java's own CLI dispatch (docs/decisions/029): --language java
    must route `oah map` through oah/discovery/java_adapter.py, not
    silently no-op or fall back to the Python adapter."""
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "App.java").write_text(
        "import com.anthropic.client.okhttp.AnthropicOkHttpClient;\n"
        "public class App {\n"
        "    void run() {\n"
        "        var client = AnthropicOkHttpClient.fromEnv();\n"
        "        client.messages().create(null);\n"
        "    }\n"
        "}\n"
    )
    _init_git_repo(target)

    workdir = tmp_path / "workdir"
    workdir.mkdir()
    out = workdir / "sm.json"
    result = _run(["map", str(target), "--language", "java",
                   "--run-id", "java-run", "-o", str(out)], cwd=workdir)
    assert result.returncode == 0, result.stderr

    surface_map = json.loads(out.read_text())
    assert surface_map["repo"]["primary_language"] == "java"
    assert surface_map["coverage_stats"]["points_total"] == 1
    assert surface_map["points"][0]["kind"] == "llm_generation"

    manifest = json.loads((workdir / ".oah" / "runs" / "java-run.json").read_text())
    assert manifest["target"]["primary_language"] == "java"
    assert manifest["stages_completed"] == ["s1"]


def test_map_pack_service_dispatches_to_express_registry(tmp_path):
    """E12 phase 3 (docs/decisions/018): --pack service must actually reach
    the service pack's Express registry through the real CLI, not just at
    the adapter's own module level -- proving oah/cli.py's _load_pack_for_args
    threading is real, not just accepted-and-dropped."""
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.ts").write_text(
        'import express from "express";\n'
        "const app = express();\n"
        'app.get("/bookings/:id", (req, res) => { res.send("ok"); });\n'
    )
    _init_git_repo(target)

    workdir = tmp_path / "workdir"
    workdir.mkdir()
    out = workdir / "sm.json"
    result = _run(["map", str(target), "--language", "typescript", "--pack", "service",
                   "--run-id", "service-run", "-o", str(out)], cwd=workdir)
    assert result.returncode == 0, result.stderr

    surface_map = json.loads(out.read_text())
    assert surface_map["coverage_stats"]["points_total"] == 1
    assert surface_map["points"][0]["kind"] == "http_server_route"
    assert surface_map["points"][0]["has_path_parameter"] is True


def test_map_default_pack_genai_never_detects_express_routes(tmp_path):
    """Zero behavior change for the default: --language typescript with no
    --pack (defaults to genai) must not pick up Express routes -- that
    vocabulary belongs to the service pack only."""
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.ts").write_text(
        'import express from "express";\n'
        "const app = express();\n"
        'app.get("/bookings/:id", (req, res) => { res.send("ok"); });\n'
    )
    _init_git_repo(target)

    workdir = tmp_path / "workdir"
    workdir.mkdir()
    result = _run(["map", str(target), "--language", "typescript", "--run-id", "genai-default-run"], cwd=workdir)
    assert result.returncode == 0, result.stderr
    surface_map = json.loads(result.stdout)
    assert surface_map["coverage_stats"]["points_total"] == 0
