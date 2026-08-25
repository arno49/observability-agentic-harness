#!/usr/bin/env python3
"""Validate a JSON file against a JSON Schema file.

Usage: python3 scripts/validate.py <schema.json> <data.json>

Exit codes: 0 = valid, 1 = invalid, 2 = usage or setup error.

Not part of the OAH pipeline — a copy of this script is injected into each
skill's scripts/ folder at bundle time (see .github/workflows/bundle-skills.yml)
so a skill can validate its own output during a hand-run session, before the
real pipeline shell exists to enforce this automatically.
"""
import json
import sys


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: validate.py <schema.json> <data.json>", file=sys.stderr)
        return 2

    schema_path, data_path = sys.argv[1], sys.argv[2]

    try:
        from jsonschema.validators import validator_for
    except ImportError:
        print("jsonschema is not installed — run: pip install jsonschema", file=sys.stderr)
        return 2

    try:
        with open(schema_path) as f:
            schema = json.load(f)
        with open(data_path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"could not read/parse input: {e}", file=sys.stderr)
        return 2

    validator_cls = validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)

    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if not errors:
        print(f"OK — {data_path} is valid against {schema_path}")
        return 0

    for e in errors:
        loc = "/".join(str(p) for p in e.path) or "(root)"
        print(f"FAIL at {loc}: {e.message}", file=sys.stderr)
    print(f"{len(errors)} error(s)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
