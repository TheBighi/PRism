"""
app/core/container_runner.py

Fetches the requested commits with a GitHub installation token, then launches
an ephemeral, locked-down Docker container to run the analysis pipeline,
then reads back a single normalized JSON array from its stdout.

The container image is built from Dockerfile.analysis and expects to be
invoked as:

    <mounted_repo> <base_sha> <head_sha> <filename1> [filename2 ...]

and to print exactly one JSON array to stdout on success.
"""

import base64
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path

import docker
import requests
from docker.errors import APIError, ImageNotFound, NotFound

logger = logging.getLogger(__name__)

ANALYSIS_IMAGE = "pr-analysis:latest"
CONTAINER_TIMEOUT_S = 900


class AnalysisError(Exception):
    """Raised for any failure in the containerized analysis pipeline —
    covers image issues, container failures, timeouts, and bad output."""


def _prepare_repository(
    clone_url: str,
    token: str,
    base_sha: str,
    head_sha: str,
    destination: Path,
) -> None:
    credentials = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    git_env = os.environ.copy()
    git_env.update({
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.extraHeader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Basic {credentials}",
        "GIT_TERMINAL_PROMPT": "0",
    })

    try:
        subprocess.run(
            ["git", "init", "--bare", "-q", str(destination)],
            check=True,
            capture_output=True,
            text=True,
        )
        for name, sha in (("base", base_sha), ("head", head_sha)):
            subprocess.run(
                ["git", "-C", str(destination), "fetch", "-q", "--depth", "1", clone_url, sha],
                check=True,
                capture_output=True,
                text=True,
                env=git_env,
            )
            subprocess.run(
                ["git", "-C", str(destination), "update-ref", f"refs/prism/{name}", "FETCH_HEAD"],
                check=True,
                capture_output=True,
                text=True,
            )
    except subprocess.CalledProcessError as e:
        raise AnalysisError(
            f"authenticated repository fetch failed: {e.stderr.strip() or 'git command failed'}"
        ) from e


def run_analysis_in_container(
    clone_url: str,
    installation_token: str,
    base_sha: str,
    head_sha: str,
    filenames: list[str],
) -> list[dict]:
    if not filenames:
        return []

    client = docker.from_env()
    staging = tempfile.TemporaryDirectory(prefix="pr-analysis-source-")
    source_repo = Path(staging.name) / "repo.git"
    try:
        _prepare_repository(clone_url, installation_token, base_sha, head_sha, source_repo)
    except Exception:
        staging.cleanup()
        raise

    try:
        container = client.containers.run(
            ANALYSIS_IMAGE,
            command=["/input/repo.git", base_sha, head_sha, *filenames],
            detach=True,
            network_mode="bridge",        # needed for git fetch + npm audit registry calls
            volumes={str(source_repo): {"bind": "/input/repo.git", "mode": "ro"}},
            environment={
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "safe.directory",
                "GIT_CONFIG_VALUE_0": "/input/repo.git",
            },
            mem_limit="2g",
            nano_cpus=500_000_000,        # ~0.5 CPU
            pids_limit=256,               # cap fork bombs / runaway subprocesses
            read_only=True,               # root fs immutable...
            tmpfs={"/tmp": "size=2g,mode=1777"},  # ...except bounded analysis working space
            security_opt=["no-new-privileges"],
            cap_drop=["ALL"],
            user="runner",
        )
    except ImageNotFound:
        staging.cleanup()
        raise AnalysisError(
            f"analysis image '{ANALYSIS_IMAGE}' not found — "
            f"build it with: docker build -f Dockerfile.analysis -t {ANALYSIS_IMAGE} ."
        )
    except APIError as e:
        staging.cleanup()
        raise AnalysisError(f"failed to start analysis container: {e}")

    try:
        try:
            result = container.wait(timeout=CONTAINER_TIMEOUT_S)
        except (APIError, requests.RequestException) as e:
            # covers the client-side wait() timing out (requests raises
            # ReadTimeout on the socket read) - container may still be
            # running on the daemon side, so make sure to stop it before removal
            try:
                container.stop(timeout=5)
            except (APIError, NotFound):
                pass
            raise AnalysisError(f"analysis container timed out or lost connection: {e}")

        stdout = container.logs(stdout=True, stderr=False).decode(errors="replace")
        stderr = container.logs(stdout=False, stderr=True).decode(errors="replace")

        if result["StatusCode"] != 0:
            raise AnalysisError(
                f"analysis container exited {result['StatusCode']}: {stderr.strip() or '(no stderr)'}"
            )

        try:
            results = json.loads(stdout)
        except json.JSONDecodeError as e:
            raise AnalysisError(
                f"could not parse container output as JSON: {e}\n"
                f"stdout was: {stdout[:500]!r}"
            )

        if not isinstance(results, list):
            raise AnalysisError(f"expected a JSON array from container, got: {type(results).__name__}")

        return results

    finally:
        try:
            container.remove(force=True)
        except (APIError, NotFound):
            logger.warning("failed to remove analysis container %s during cleanup", container.id)
        staging.cleanup()
