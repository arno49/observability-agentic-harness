#!/usr/bin/env python3
"""Check that one or more files are well-formed JSON Schema documents.

Usage: python3 check_schema.py <schema.json> [<schema.json> ...]
Exit codes: 0 = all valid, 1 = at least one invalid, 2 = usage/setup error.

CI-only tooling for .github/workflows/bundle-skills.yml — unlike validate.py
in this same directory, this script is never injected into a skill's bundle.
"""
import json
import sys


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: check_schema.py <schema.json> [...]", file=sys.stderr)
        return 2

    try:
        from jsonschema.validators import validator_for
    except ImportError:
        print("jsonschema is not installed — run: pip install jsonschema", file=sys.stderr)
        return 2

    fail = False
    for path in sys.argv[1:]:
        try:
            with open(path) as f:
                schema = json.load(f)
            validator_for(schema).check_schema(schema)
        except Exception as e:
            print(f"FAIL {path}: {e}", file=sys.stderr)
            fail = True
        else:
            print(f"OK   {path}")

    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
