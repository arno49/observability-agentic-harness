"""Regression tests for oah.validate.checker -- R4 (static-only): does a
DTO's expected attribute names appear in the applied file, at or after
its anchor line. No agent, no LLM, no execution of target code at all --
these are all real file reads against real DTO/instrument-result shapes,
nothing mocked."""
from oah.validate.checker import check_dto_static

DTO = {
    "id": "dto-0001", "gap_id": "gap-0001", "surface_point_ids": ["sp-0001"],
    "change": {
        "type": "wrap_call", "file": "app.py",
        "anchor": "response = client.messages.create(",
        "preconditions": ["a direct client.messages.create(...) call"],
        "description": "wrap with a span",
    },
    "expected_events": [{"event_type": "generation",
                          "required_attributes": ["gen_ai.usage.input_tokens", "gen_ai.request.model"]}],
    "rollout_step": 1,
}

APPLIED_RESULT = {"dto_id": "dto-0001", "status": "applied", "commit_sha": "abc123",
                   "reason": None, "syntax_valid": True}


def _write_target(tmp_path, content):
    target = tmp_path / "target_repo"
    target.mkdir()
    (target / "app.py").write_text(content)
    return target


def test_present_when_all_required_attributes_appear_after_the_anchor(tmp_path):
    target = _write_target(tmp_path, (
        "import telemetry\n"
        "def answer():\n"
        "    response = client.messages.create(model='x')\n"
        "    telemetry.emit(gen_ai_usage_input_tokens='gen_ai.usage.input_tokens', "
        "gen_ai_request_model='gen_ai.request.model')\n"
    ))
    result = check_dto_static(DTO, APPLIED_RESULT, target)
    assert result["status"] == "present"
    assert result["missing_attributes"] is None


def test_absent_names_the_missing_attributes(tmp_path):
    target = _write_target(tmp_path, (
        "def answer():\n"
        "    response = client.messages.create(model='x')\n"
        "    telemetry.emit('gen_ai.usage.input_tokens')\n"
    ))
    result = check_dto_static(DTO, APPLIED_RESULT, target)
    assert result["status"] == "absent"
    assert result["missing_attributes"] == ["gen_ai.request.model"]


def test_attribute_present_before_the_anchor_does_not_count(tmp_path):
    """A DTO's own instrumentation must appear at/after its anchor -- a
    coincidental match earlier in the file (e.g. a docstring, or a
    different DTO's own instrumentation) shouldn't count as evidence for
    this DTO."""
    target = _write_target(tmp_path, (
        "# see also gen_ai.usage.input_tokens and gen_ai.request.model in the docs\n"
        "def answer():\n"
        "    response = client.messages.create(model='x')\n"
    ))
    result = check_dto_static(DTO, APPLIED_RESULT, target)
    assert result["status"] == "absent"
    assert set(result["missing_attributes"]) == {"gen_ai.usage.input_tokens", "gen_ai.request.model"}


def test_skipped_when_instrument_result_is_none(tmp_path):
    target = _write_target(tmp_path, "response = client.messages.create(model='x')\n")
    result = check_dto_static(DTO, None, target)
    assert result["status"] == "skipped"
    assert "not present" in result["reason"]


def test_skipped_when_dto_was_refused_not_applied(tmp_path):
    target = _write_target(tmp_path, "response = client.messages.create(model='x')\n")
    refused = {"dto_id": "dto-0001", "status": "refused", "commit_sha": None,
               "reason": "anchor mismatch", "syntax_valid": None}
    result = check_dto_static(DTO, refused, target)
    assert result["status"] == "skipped"
    assert "refused" in result["reason"]


def test_skipped_when_target_file_missing(tmp_path):
    target = tmp_path / "target_repo"
    target.mkdir()
    result = check_dto_static(DTO, APPLIED_RESULT, target)
    assert result["status"] == "skipped"
    assert "app.py" in result["reason"]


def test_skipped_when_anchor_no_longer_found():
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        target = Path(d)
        (target / "app.py").write_text("def answer():\n    pass\n")
        result = check_dto_static(DTO, APPLIED_RESULT, target)
        assert result["status"] == "skipped"
        assert "anchor" in result["reason"]
