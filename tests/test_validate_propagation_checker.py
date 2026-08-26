"""oah/validate/propagation_checker.py -- pure function, no sandbox."""
from oah.validate.propagation_checker import check_dto_propagation

APPLIED = {"dto_id": "dto-0001", "status": "applied", "commit_sha": "abc123", "reason": None, "syntax_valid": True}


def _dto(description, change_type="propagate_context", anchor="asyncio.create_task(worker())"):
    return {
        "id": "dto-0001", "gap_id": "gap-0001", "surface_point_ids": ["sp-0001"],
        "change": {"type": change_type, "file": "app.py", "anchor": anchor,
                   "preconditions": [], "description": description},
        "expected_events": [{"event_type": "span", "required_attributes": []}],
        "rollout_step": 1,
    }


def test_not_applicable_for_a_non_propagate_context_dto():
    dto = _dto("wrap this call", change_type="wrap_call")
    result = check_dto_propagation(dto, APPLIED, "/nonexistent")
    assert result == {"dto_id": "dto-0001", "status": "not_applicable", "reason": "this checker only evaluates propagate_context DTOs"}


def test_skipped_when_instrument_result_is_missing(tmp_path):
    dto = _dto("thread pool submit crosses into a new context")
    result = check_dto_propagation(dto, None, tmp_path)
    assert result["status"] == "skipped"
    assert "not present" in result["reason"]


def test_skipped_when_instrument_result_status_is_not_applied(tmp_path):
    dto = _dto("thread pool submit")
    refused = {"dto_id": "dto-0001", "status": "refused", "commit_sha": None, "reason": "x", "syntax_valid": None}
    result = check_dto_propagation(dto, refused, tmp_path)
    assert result["status"] == "skipped"


def test_skipped_when_target_file_missing(tmp_path):
    dto = _dto("thread pool submit")
    result = check_dto_propagation(dto, APPLIED, tmp_path)
    assert result["status"] == "skipped"
    assert "does not exist" in result["reason"]


def test_skipped_when_anchor_not_found(tmp_path):
    (tmp_path / "app.py").write_text("def other():\n    pass\n")
    dto = _dto("thread pool submit")
    result = check_dto_propagation(dto, APPLIED, tmp_path)
    assert result["status"] == "skipped"
    assert "anchor" in result["reason"]


def test_asyncio_boundary_is_present_with_no_explicit_code_required(tmp_path):
    (tmp_path / "app.py").write_text("def handler():\n    asyncio.create_task(worker())\n")
    dto = _dto("dispatch across an asyncio.create_task boundary")
    result = check_dto_propagation(dto, APPLIED, tmp_path)
    assert result == {"dto_id": "dto-0001", "status": "present", "reason": None}


def test_thread_boundary_present_when_both_markers_found(tmp_path):
    (tmp_path / "app.py").write_text(
        "def handler():\n"
        "    executor.submit(worker)\n"
        "    ctx = context.get_current()\n"
        "    context.attach(ctx)\n"
    )
    dto = _dto("submitted to a thread pool executor", anchor="executor.submit(worker)")
    result = check_dto_propagation(dto, APPLIED, tmp_path)
    assert result["status"] == "present"


def test_thread_boundary_absent_when_markers_missing(tmp_path):
    (tmp_path / "app.py").write_text("def handler():\n    executor.submit(worker)\n")
    dto = _dto("submitted to a thread pool executor", anchor="executor.submit(worker)")
    result = check_dto_propagation(dto, APPLIED, tmp_path)
    assert result["status"] == "absent"
    assert "thread" in result["reason"]


def test_queue_boundary_present_when_propagate_inject_found(tmp_path):
    (tmp_path / "app.py").write_text(
        "def handler():\n"
        "    celery_task.delay(headers=carrier)\n"
        "    propagate.inject(carrier)\n"
    )
    dto = _dto("dispatched via a celery queue task", anchor="celery_task.delay(headers=carrier)")
    result = check_dto_propagation(dto, APPLIED, tmp_path)
    assert result["status"] == "present"


def test_queue_boundary_absent_when_markers_missing(tmp_path):
    (tmp_path / "app.py").write_text("def handler():\n    celery_task.delay()\n")
    dto = _dto("dispatched via a celery queue task", anchor="celery_task.delay()")
    result = check_dto_propagation(dto, APPLIED, tmp_path)
    assert result["status"] == "absent"


def test_unclassifiable_description_is_skipped_not_guessed(tmp_path):
    (tmp_path / "app.py").write_text("def handler():\n    do_the_thing()\n")
    dto = _dto("moves work somewhere else", anchor="do_the_thing()")
    result = check_dto_propagation(dto, APPLIED, tmp_path)
    assert result["status"] == "skipped"
    assert "could not classify" in result["reason"]
