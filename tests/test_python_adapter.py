"""Regression tests for oah.discovery.python_adapter.

The real-world recall claim (100% on a 3-repo corpus) is proven and
documented in docs/decisions/003-sp1-ast-recall.md — these tests don't
re-clone that corpus on every run. Their job is regression protection for
the specific behaviors that claim depends on, using small deterministic
fixtures so CI never depends on network access or an external repo's
continued existence.
"""
import json
import tempfile
from pathlib import Path

import pytest

from oah.discovery.python_adapter import detect_file, build_surface_map
from oah.schemas import validate, SchemaValidationError


def _write(tmp_path, name, content):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def _detect(tmp_path, content, filename="app.py"):
    path = _write(tmp_path, filename, content)
    return detect_file(path, tmp_path, [1])


def test_direct_call_resolved(tmp_path):
    resolved, ambiguous = _detect(tmp_path, """
import anthropic
client = anthropic.Anthropic()
response = client.messages.create(model="x")
""")
    assert len(resolved) == 1
    assert ambiguous == []
    assert resolved[0]["kind"] == "llm_generation"
    assert resolved[0]["framework"] == "anthropic-sdk"
    assert resolved[0]["detection"] == "signature"


def test_from_import_alias_form_resolved(tmp_path):
    """`from anthropic import Anthropic as A` — the other real import form
    found in the corpus (claude-engineer's main.py)."""
    resolved, ambiguous = _detect(tmp_path, """
from anthropic import Anthropic as A
client = A()
response = client.messages.create(model="x")
""")
    assert len(resolved) == 1
    assert ambiguous == []


def test_beta_namespace_suffix_match(tmp_path):
    """client.beta.prompt_caching.messages.create — suffix match, not exact
    path match. Real pattern from claude-engineer's corpus repo."""
    resolved, _ = _detect(tmp_path, """
import anthropic
client = anthropic.Anthropic()
response = client.beta.prompt_caching.messages.create(model="x")
""")
    assert len(resolved) == 1


def test_self_attr_class_prescan(tmp_path):
    """self._client set in __init__, read in a different method — needed
    class-scoped prescan, not just same-statement tracking."""
    resolved, _ = _detect(tmp_path, """
import anthropic

class Provider:
    def __init__(self):
        self._client = anthropic.Anthropic()

    def complete(self):
        return self._client.messages.stream(model="x")
""")
    assert len(resolved) == 1
    assert resolved[0]["symbol"] == "Provider.complete"


def test_typed_parameter_resolved(tmp_path):
    resolved, _ = _detect(tmp_path, """
import anthropic

def run(client: anthropic.Anthropic):
    return client.messages.create(model="x")
""")
    assert len(resolved) == 1
    assert resolved[0]["symbol"] == "run"


def test_other_sdk_receiver_flagged_ambiguous_not_misclassified(tmp_path):
    """The real ollama-eng.py trap from SP1's corpus: `client` is provably
    ollama.AsyncClient(), not Anthropic, but the registry is Anthropic-only
    (no positive evidence either way for a different SDK) — per
    docs/decisions/003-sp1-ast-recall.md finding 4, the correct outcome is
    low-confidence-flagged-for-disambiguation, not a silent drop and not a
    confident anthropic-sdk misclassification."""
    resolved, ambiguous = _detect(tmp_path, """
import ollama
client = ollama.AsyncClient()
response = client.messages.create(model="x")
""")
    assert resolved == []
    assert len(ambiguous) == 1


def test_unresolved_receiver_flagged_ambiguous_not_dropped(tmp_path):
    """Subscript-indexed receiver: suffix matches, root isn't a plain name
    or self-attr — must be flagged for disambiguation, never silently
    dropped."""
    resolved, ambiguous = _detect(tmp_path, """
import anthropic
clients = {"primary": anthropic.Anthropic()}
response = clients["primary"].messages.create(model="x")
""")
    assert resolved == []
    assert len(ambiguous) == 1
    assert ambiguous[0]["scanner_kind"] is None


def test_dynamic_dispatch_is_a_true_miss(tmp_path):
    """getattr(client.messages, method_name)(...) — no `.create`/`.stream`
    token exists anywhere in the source for a suffix match to find. This is
    the documented, accepted boundary (docs/decisions/003), not a bug."""
    resolved, ambiguous = _detect(tmp_path, """
import anthropic
import os
client = anthropic.Anthropic()
method_name = os.environ.get("LLM_METHOD", "create")
response = getattr(client.messages, method_name)(model="x")
""")
    assert resolved == []
    assert ambiguous == []


def test_ambiguous_candidate_matches_disambiguation_input_schema(tmp_path):
    resolved, ambiguous = _detect(tmp_path, """
import anthropic
clients = {"primary": anthropic.Anthropic()}
response = clients["primary"].messages.create(model="x")
""")
    batch = {"schema_version": "0.1.0", "candidates": ambiguous}
    # Not registered under oah/schemas.py's SCHEMAS_DIR (it's a skill-local
    # schema), so load and validate it directly here.
    schema = json.loads(
        Path("skills/s1-surface-mapper/io/input.schema.json").read_text()
    )
    from jsonschema import Draft202012Validator
    errors = list(Draft202012Validator(schema).iter_errors(batch))
    assert errors == [], errors


def test_build_surface_map_validates_against_real_schema(tmp_path):
    _write(tmp_path, "app.py", """
import anthropic
client = anthropic.Anthropic()
response = client.messages.create(model="x")
""")
    surface_map, still_ambiguous = build_surface_map(tmp_path, git_sha="deadbeef")
    validate("surface_map", surface_map)  # raises on failure
    assert surface_map["coverage_stats"]["points_total"] == 1
    assert still_ambiguous == []


def test_build_surface_map_merges_disambiguation_results(tmp_path):
    _write(tmp_path, "app.py", """
import anthropic
clients = {"primary": anthropic.Anthropic()}
response = clients["primary"].messages.create(model="x")
""")
    surface_map, still_ambiguous = build_surface_map(tmp_path, git_sha="deadbeef")
    assert surface_map["points"] == []
    assert len(still_ambiguous) == 1

    candidate_id = still_ambiguous[0]["candidate_id"]
    disambiguated = [{
        "candidate_id": candidate_id,
        "kind": "llm_generation",
        "framework": "anthropic-sdk",
        "confidence": 0.9,
        "detection": "llm_disambiguation",
    }]
    surface_map2, still_ambiguous2 = build_surface_map(
        tmp_path, git_sha="deadbeef", disambiguated=disambiguated
    )
    validate("surface_map", surface_map2)
    assert len(surface_map2["points"]) == 1
    assert surface_map2["points"][0]["detection"] == "llm_disambiguation"
    assert still_ambiguous2 == []


def test_rejected_disambiguation_candidate_never_enters_surface_map(tmp_path):
    """kind: null from the disambiguation skill is a correct rejection
    (skills/s1-surface-mapper/SKILL.md) — it must never be smuggled into
    surface_map.json, whose kind enum has no null member."""
    _write(tmp_path, "app.py", """
import anthropic
clients = {"primary": anthropic.Anthropic()}
response = clients["primary"].messages.create(model="x")
""")
    _, still_ambiguous = build_surface_map(tmp_path, git_sha="deadbeef")
    candidate_id = still_ambiguous[0]["candidate_id"]
    disambiguated = [{"candidate_id": candidate_id, "kind": None, "confidence": 0.9,
                       "detection": "llm_disambiguation", "notes": "dead-code-candidate"}]
    surface_map, still_ambiguous2 = build_surface_map(
        tmp_path, git_sha="deadbeef", disambiguated=disambiguated
    )
    validate("surface_map", surface_map)


# --- Second registry (pinecone -> retrieval) --------------------------------
# Confirms oah/discovery/registry.py's REGISTRIES generalization actually
# resolves a second SDK end to end, not just the original anthropic one.

def test_pinecone_direct_call_resolved_as_retrieval(tmp_path):
    resolved, ambiguous = _detect(tmp_path, """
import pinecone
pinecone.init(api_key="x", environment="y")
index = pinecone.Index("my-index")
results = index.query(vector=[0.1, 0.2], top_k=5)
""")
    assert len(resolved) == 1
    assert ambiguous == []
    assert resolved[0]["kind"] == "retrieval"
    assert resolved[0]["framework"] == "pinecone-sdk"
    assert resolved[0]["detection"] == "signature"


def test_two_registries_in_one_file_both_resolved_independently(tmp_path):
    """anthropic's two-segment suffix and pinecone's one-segment suffix
    must both match correctly in the same file without either registry's
    receiver tracking bleeding into the other's."""
    resolved, ambiguous = _detect(tmp_path, """
import anthropic
import pinecone

client = anthropic.Anthropic()
pinecone.init(api_key="x", environment="y")
index = pinecone.Index("my-index")

results = index.query(vector=[0.1, 0.2], top_k=5)
message = client.messages.create(model="x")
""")
    assert ambiguous == []
    kinds = {r["kind"] for r in resolved}
    assert kinds == {"retrieval", "llm_generation"}


def test_pinecone_self_attr_class_prescan(tmp_path):
    resolved, _ = _detect(tmp_path, """
import pinecone

class Retriever:
    def __init__(self):
        self._index = pinecone.Index("my-index")

    def search(self, vector):
        return self._index.query(vector=vector, top_k=5)
""")
    assert len(resolved) == 1
    assert resolved[0]["kind"] == "retrieval"
    assert resolved[0]["symbol"] == "Retriever.search"


def test_unrelated_query_call_on_unresolved_receiver_flagged_ambiguous_not_misclassified(tmp_path):
    """A SQLAlchemy-style `session.query(...)` shares pinecone's suffix but
    resolves to a different (unresolvable) receiver -- registry.py's own
    stated tradeoff: this must land in the ambiguous bucket for
    disambiguation, never be silently accepted as retrieval and never be
    silently dropped."""
    resolved, ambiguous = _detect(tmp_path, """
import sqlalchemy
session = sqlalchemy.orm.Session()
result = session.query(User).all()
""")
    assert resolved == []
    assert len(ambiguous) == 1


def test_pinecone_receiver_resolved_to_anthropic_module_is_true_negative(tmp_path):
    """A variable bound to the anthropic client that happens to have a
    `.query(...)` call on it (not a real pattern, but exercises the
    resolved-to-a-known-but-wrong-registry path) must be a true negative,
    not misreported as retrieval or flagged ambiguous -- the receiver IS
    resolved, just not to a registry that declares this suffix."""
    resolved, ambiguous = _detect(tmp_path, """
import anthropic
client = anthropic.Anthropic()
result = client.query(vector=[0.1])
""")
    assert resolved == []
    assert ambiguous == []
