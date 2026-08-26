"""Loads a domain pack manifest: domains/<name>/pack.json, validated against
schemas/domain_pack.schema.json the same way every other stage boundary in
this codebase is validated (oah/schemas.py). Pure and deterministic -- no LLM
call, no network -- so pipeline core can call this unconditionally on every
command that used to hold GenAI literals directly (see docs/decisions/011).

domains/ follows the exact resolve_dir() convention schemas/ and skills/
already use (oah/_resources.py): repo-root in a dev/editable install, bundled
under oah/_bundled/domains/ in a built wheel. Detector *code* a pack needs
(e.g. a structural_pattern matcher) lives under oah/domains/<name>/ instead --
real Python, shipped as part of the oah package itself, not pack data.
"""
import json

from oah._resources import resolve_dir
from oah.schemas import validate, SchemaValidationError

DOMAINS_DIR = resolve_dir("domains")


class DomainPackError(Exception):
    """A caller must treat this as 'no pack loaded', never catch it and
    fabricate a partial manifest."""


def load_pack(name):
    """name is the pack's directory name under domains/, e.g. 'genai'.
    Returns the parsed, schema-validated manifest dict. Raises
    DomainPackError loudly on a missing pack or one that fails validation
    -- never silently loads a partial or unvalidated manifest."""
    path = DOMAINS_DIR / name / "pack.json"
    if not path.is_file():
        raise DomainPackError(f"no domain pack named {name!r} at {path}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise DomainPackError(f"{path} is not valid JSON: {e}") from e
    try:
        validate("domain_pack", data)
    except SchemaValidationError as e:
        raise DomainPackError(f"{path} does not match domain_pack.schema.json: {e}") from e
    return data
