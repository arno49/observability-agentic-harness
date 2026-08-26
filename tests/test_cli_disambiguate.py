"""In-process test for cmd_map's disambiguation merge path — subprocess
tests (test_cli.py) can't easily mock litellm inside a child process, and
disambiguate.py's own tests (test_disambiguate.py) don't exercise cli.py's
wiring: the checkpoint-and-merge logic that turns a disambiguation result
into a re-built surface_map.json. This is that missing link, mocked at the
oah.discovery.disambiguate.disambiguate boundary."""
import argparse
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from oah.cli import cmd_map


def _init_git_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t.com", "-c", "user.name=t",
                     "commit", "--allow-empty", "-q", "-m", "init"], cwd=path, check=True)


def test_successful_disambiguation_merges_into_surface_map(tmp_path, monkeypatch):
    target = tmp_path / "target_repo"
    target.mkdir()
    # A subscript-indexed receiver: unresolved by the deterministic pass,
    # a real ambiguous candidate (same shape as SP1's synthetic hard case).
    (target / "app.py").write_text(
        "import anthropic\n"
        "clients = {'primary': anthropic.Anthropic()}\n"
        "response = clients['primary'].messages.create(model='x')\n"
    )
    _init_git_repo(target)
    monkeypatch.chdir(tmp_path)

    def fake_disambiguate(candidates, model=None):
        assert len(candidates) == 1
        return [{
            "candidate_id": candidates[0]["candidate_id"],
            "kind": "llm_generation",
            "framework": "anthropic-sdk",
            "confidence": 0.85,
            "detection": "llm_disambiguation",
        }]

    args = argparse.Namespace(
        target=str(target), output=str(tmp_path / "sm.json"),
        run_id="disambig-run", no_disambiguate=False,
    )
    with patch("oah.discovery.disambiguate.missing_credentials", return_value=None), \
         patch("oah.discovery.disambiguate.disambiguate", side_effect=fake_disambiguate):
        rc = cmd_map(args)

    assert rc == 0
    surface_map = json.loads((tmp_path / "sm.json").read_text())
    assert len(surface_map["points"]) == 1
    assert surface_map["points"][0]["detection"] == "llm_disambiguation"
    assert surface_map["points"][0]["kind"] == "llm_generation"
    assert not (tmp_path / "sm.ambiguous.json").exists()  # nothing left unresolved


def test_disambiguation_checkpointed_independently_from_scan(tmp_path, monkeypatch):
    """A crash between scan and disambiguate must resume from disambiguate,
    not redo the scan or fail to find its result."""
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text(
        "import anthropic\n"
        "clients = {'primary': anthropic.Anthropic()}\n"
        "response = clients['primary'].messages.create(model='x')\n"
    )
    _init_git_repo(target)
    monkeypatch.chdir(tmp_path)

    call_count = {"n": 0}

    def fake_disambiguate(candidates, model=None):
        call_count["n"] += 1
        return [{
            "candidate_id": candidates[0]["candidate_id"], "kind": "llm_generation",
            "confidence": 0.85, "detection": "llm_disambiguation",
        }]

    args1 = argparse.Namespace(target=str(target), output=str(tmp_path / "sm1.json"),
                                run_id="resume-run", no_disambiguate=False)
    with patch("oah.discovery.disambiguate.missing_credentials", return_value=None), \
         patch("oah.discovery.disambiguate.disambiguate", side_effect=fake_disambiguate):
        cmd_map(args1)
    assert call_count["n"] == 1

    # Second run, same run_id: must reuse the checkpointed disambiguation
    # result, not call the model again.
    args2 = argparse.Namespace(target=str(target), output=str(tmp_path / "sm2.json"),
                                run_id="resume-run", no_disambiguate=False)
    with patch("oah.discovery.disambiguate.missing_credentials", return_value=None), \
         patch("oah.discovery.disambiguate.disambiguate", side_effect=fake_disambiguate):
        cmd_map(args2)
    assert call_count["n"] == 1  # unchanged -- reused the checkpoint

    assert json.loads((tmp_path / "sm1.json").read_text()) == json.loads((tmp_path / "sm2.json").read_text())


# --- Run-manifest honesty (found by adversarial review) --------------------
# cmd_map used to mark "s1" completed in both run_manifest.json and the
# state DB unconditionally, even when disambiguation never actually
# resolved every candidate -- an audit record (run_manifest.json's own
# documented purpose) that claims a stage finished when it didn't.

def test_manifest_not_marked_complete_when_disambiguation_credentials_missing(tmp_path, monkeypatch):
    from oah import run_manifest as rm

    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text(
        "import anthropic\n"
        "clients = {'primary': anthropic.Anthropic()}\n"
        "response = clients['primary'].messages.create(model='x')\n"
    )
    _init_git_repo(target)
    monkeypatch.chdir(tmp_path)

    args = argparse.Namespace(
        target=str(target), output=str(tmp_path / "sm.json"),
        run_id="no-creds-run", no_disambiguate=False,
    )
    with patch("oah.discovery.disambiguate.missing_credentials", return_value="ANTHROPIC_API_KEY is not set"):
        rc = cmd_map(args)

    assert rc == 0
    manifest = rm.load("no-creds-run")
    assert "s1" not in manifest["stages_completed"]
    assert manifest["completed_at"] is None


def test_manifest_not_marked_complete_when_no_disambiguate_flag_leaves_candidates_unresolved(tmp_path, monkeypatch):
    from oah import run_manifest as rm

    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text(
        "import anthropic\n"
        "clients = {'primary': anthropic.Anthropic()}\n"
        "response = clients['primary'].messages.create(model='x')\n"
    )
    _init_git_repo(target)
    monkeypatch.chdir(tmp_path)

    args = argparse.Namespace(
        target=str(target), output=str(tmp_path / "sm.json"),
        run_id="skip-disambig-run", no_disambiguate=True,
    )
    rc = cmd_map(args)

    assert rc == 0
    manifest = rm.load("skip-disambig-run")
    assert "s1" not in manifest["stages_completed"]
    assert manifest["completed_at"] is None


def test_manifest_marked_complete_when_no_ambiguous_candidates_exist(tmp_path, monkeypatch):
    """The common, simple case (nothing ambiguous at all) must still mark
    s1 complete -- this fix must not regress the honest-and-true case."""
    from oah import run_manifest as rm

    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text(
        "import anthropic\n"
        "client = anthropic.Anthropic()\n"
        "response = client.messages.create(model='x')\n"
    )
    _init_git_repo(target)
    monkeypatch.chdir(tmp_path)

    args = argparse.Namespace(
        target=str(target), output=str(tmp_path / "sm.json"),
        run_id="clean-run", no_disambiguate=False,
    )
    rc = cmd_map(args)

    assert rc == 0
    manifest = rm.load("clean-run")
    assert "s1" in manifest["stages_completed"]
    assert manifest["completed_at"] is not None
