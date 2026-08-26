"""Schema validation at every stage boundary.

Per CLAUDE.md: "Do not add pipeline code that passes free text between
stages; every boundary is a schema-validated artifact." This is the one
function every stage's output goes through before the next stage is allowed
to read it.
"""
import json

from jsonschema import Draft202012Validator

from oah._resources import resolve_dir

SCHEMAS_DIR = resolve_dir("schemas")


class SchemaValidationError(Exception):
    def __init__(self, schema_name, errors):
        self.schema_name = schema_name
        self.errors = errors
        joined = "; ".join(f"{'/'.join(str(p) for p in e.path)}: {e.message}" for e in errors)
        super().__init__(f"{schema_name}: {joined}")


def load_schema(name):
    """name is the schema's filename without .schema.json, e.g. 'surface_map'."""
    path = SCHEMAS_DIR / f"{name}.schema.json"
    if not path.is_file():
        raise FileNotFoundError(f"no schema named {name!r} in {SCHEMAS_DIR}")
    return json.loads(path.read_text())


def validate(name, data):
    """Raise SchemaValidationError if data doesn't conform to schemas/<name>.schema.json.
    Returns data unchanged on success, so this composes as `validate('x', produce())`."""
    schema = load_schema(name)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if errors:
        raise SchemaValidationError(name, errors)
    return data
