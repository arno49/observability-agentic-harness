"""E6 R2's execution primitive: run a shell script against a target
repo's *copy* inside an isolated, network-disabled Docker container.
This is the first place in this codebase that executes target-repo
content at all -- docs/security.md T1 (prompt injection / hostile
content) applies in a stronger form here than anywhere else so far,
since this isn't reading code, it's running it.

Isolation, each verified with a real container in
tests/test_sandbox_docker.py, not assumed from the flags alone:
- No bind mount to the host filesystem at any point. The target repo
  is copied into a throwaway image *once*, at `docker build` time
  (`COPY . /repo`, context = target_repo, but the generated Dockerfile
  itself lives in a temp dir *outside* target_repo -- never writes
  anything into the user's own working tree). The *running* container
  has no path back to the host at all.
- `--network none` on the *running* container only: no egress, no DNS,
  nothing to exfiltrate to or pull further payloads from while the
  target's own code (tests, in R2's case) is actually executing.
  `setup_script` (below) is the one deliberate exception -- it runs as
  a `RUN` instruction at `docker build` time, which Docker does not
  network-isolate, because installing named dependencies from a
  manifest (pip/npm/etc.) genuinely needs network and happens *before*
  any target test code runs. This is the same install-then-isolate
  split ordinary CI systems use; it is a real, intentional boundary,
  not an oversight -- a malicious `setup.py`/build backend could still
  run code during that install step, which is a known, accepted risk
  of installing a target's declared dependencies at all (also true of
  simply reading the target's source).
- `--memory`/`--cpus`/`--pids-limit`: bounded resource consumption.
- A wall-clock timeout via Python's own subprocess timeout, belt-and-
  suspenders with the resource flags above, not a replacement for them.
- Unconditional cleanup in a `finally` block: `docker rm -f` (a
  container that was still running when the timeout fired is not
  cleaned up by `--rm` alone -- `--rm` only fires on normal exit, which
  a killed docker-run client process never reaches) and
  `docker image rm -f`, both swallowing "already gone" errors, both run
  regardless of which path got here.

Never raises for an expected failure mode (Docker missing, daemon
unreachable, build failure, timeout) -- returns a result dict with the
failure captured in stdout/stderr/timed_out, same "never raise for an
expected failure, only for a real bug" posture as every other stage in
this codebase (apply_dto_report_only, _generate_patch, check_dto_static).
"""
import base64
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path


def docker_available():
    """True only if `docker` is on PATH *and* a live daemon actually
    answers -- the same "binary present isn't the same as working"
    lesson this session already learned once for claude-agent-sdk's
    bundled CLI (auth can be missing even when the binary imports)."""
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=10)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _sandbox_result(exit_code=None, stdout="", stderr="", timed_out=False):
    return {"exit_code": exit_code, "stdout": stdout, "stderr": stderr, "timed_out": timed_out}


def run_in_sandbox(target_repo, script, *, setup_script=None, image="python:3.12-slim",
                    timeout_s=300, memory="512m", cpus="1.0"):
    """Builds a throwaway image from target_repo's contents, runs
    `script` (a shell string) inside an isolated, network-disabled
    container, returns {exit_code, stdout, stderr, timed_out}.
    `exit_code` is None only when the sandbox itself never got as far
    as running `script` (Docker unavailable, image build failed,
    including a failure of `setup_script` itself) -- distinct from
    `script`'s own real exit code, including a real non-zero one.

    `setup_script`, if given, is baked into the image as a `RUN`
    instruction and so executes at `docker build` time -- with network
    access, unlike `script` -- for dependency installation. See the
    module docstring for why this split exists."""
    if not docker_available():
        return _sandbox_result(stderr="docker is not available (not on PATH, or the daemon is unreachable)")

    tag = f"oah-sandbox-{uuid.uuid4().hex[:12]}"
    container_name = f"oah-sandbox-run-{uuid.uuid4().hex[:12]}"

    with tempfile.TemporaryDirectory() as dockerfile_dir:
        dockerfile_path = Path(dockerfile_dir) / "Dockerfile"
        dockerfile_lines = [f"FROM {image}", "COPY . /repo", "WORKDIR /repo"]
        if setup_script:
            # base64-encoded and decoded on one RUN line: `setup_script`
            # is a multi-line shell script, and the build context here
            # is target_repo (not dockerfile_dir), so there's no COPY
            # source available to hand it in as a separate file -- and
            # a literal multi-line RUN would terminate the instruction
            # at its first newline.
            encoded = base64.b64encode(setup_script.encode()).decode()
            dockerfile_lines.append(f"RUN echo {encoded} | base64 -d | sh")
        dockerfile_path.write_text("\n".join(dockerfile_lines) + "\n")

        build = subprocess.run(
            ["docker", "build", "-f", str(dockerfile_path), "-t", tag, str(target_repo)],
            capture_output=True, text=True, timeout=timeout_s,
        )
        if build.returncode != 0:
            return _sandbox_result(stderr=f"docker build failed:\n{build.stderr}")

        try:
            run = subprocess.run(
                ["docker", "run", "--rm", "--network", "none",
                 "--memory", memory, "--cpus", cpus, "--pids-limit", "100",
                 "--name", container_name, tag, "sh", "-c", script],
                capture_output=True, text=True, timeout=timeout_s,
            )
            return _sandbox_result(exit_code=run.returncode, stdout=run.stdout, stderr=run.stderr)
        except subprocess.TimeoutExpired as e:
            return _sandbox_result(
                stdout=(e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""),
                stderr=f"sandbox timed out after {timeout_s}s",
                timed_out=True,
            )
        finally:
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
            subprocess.run(["docker", "image", "rm", "-f", tag], capture_output=True)
