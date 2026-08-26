#!/usr/bin/env python3
"""Snapshots schemas/ and skills/ into oah/_bundled/ before a wheel/sdist
build, so a real `pip install oah` (no repo checkout on the target machine)
still has its schema and skill data. See oah/_resources.py for the runtime
side of this: it prefers the repo-root directories (dev/editable install)
and falls back to this bundled copy only when those aren't present.

Run this before `python -m build` -- .github/workflows/publish-pypi.yml
does so automatically. oah/_bundled/ is gitignored: it's a build artifact,
not a second source of truth to keep in sync by hand.
"""
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
BUNDLED_DIR = REPO_ROOT / "oah" / "_bundled"


def sync(name):
    src = REPO_ROOT / name
    dst = BUNDLED_DIR / name
    if not src.is_dir():
        print(f"error: {src} does not exist -- run this from the repo root", file=sys.stderr)
        sys.exit(1)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    print(f"synced {src} -> {dst}")


if __name__ == "__main__":
    if BUNDLED_DIR.exists():
        shutil.rmtree(BUNDLED_DIR)
    sync("schemas")
    sync("skills")
