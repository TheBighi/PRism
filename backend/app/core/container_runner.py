"""
app/core/container_runner.py

Launches an ephemeral, locked-down Docker container to run the full
clone -> lint -> security-scan pipeline against an untrusted PR head commit,
then reads back a single normalized JSON array from its stdout.

The container image is built from Dockerfile.analysis and expects to be
invoked as:

    <clone_url> <head_sha> <filename1> [filename2 ...]

and to print exactly one JSON array to stdout on success.
"""

import json
import logging

import requests
import docker
from docker.errors import APIError, ImageNotFound, NotFound

logger = logging.getLogger(__name__)

ANALYSIS_IMAGE = "pr-analysis:latest"
CONTAINER_TIMEOUT_S = 240


class AnalysisError(Exception):
    """Raised for any failure in the containerized analysis pipeline —
    covers image issues, container failures, timeouts, and bad output."""
    pass


def run_analysis_in_container(clone_url: str, base_sha: str, head_sha: str, filenames: list[str]) -> list[dict]:
    if not filenames:
        return []

    client = docker.from_env()

    try:
        container = client.containers.run(
            ANALYSIS_IMAGE,
            command=[clone_url, base_sha, head_sha, *filenames],
            detach=True,
            network_mode="bridge",        # needed for git fetch + npm audit registry calls
            mem_limit="512m",
            nano_cpus=500_000_000,        # ~0.5 CPU
            pids_limit=256,               # cap fork bombs / runaway subprocesses
            read_only=True,               # root fs immutable...
            tmpfs={"/tmp": "size=256m,mode=1777"},  # ...except /tmp, which tempfile.mkdtemp needs
            security_opt=["no-new-privileges"],
            cap_drop=["ALL"],
            user="runner",
        )
    except ImageNotFound:
        raise AnalysisError(
            f"analysis image '{ANALYSIS_IMAGE}' not found — "
            f"build it with: docker build -f Dockerfile.analysis -t {ANALYSIS_IMAGE} ."
        )
    except APIError as e:
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