import asyncio
import os
import subprocess

import pytest

from app.core.container_runner import run_analysis_in_container


@pytest.mark.skipif(
    os.environ.get("RUN_DOCKER_INTEGRATION") != "1",
    reason="set RUN_DOCKER_INTEGRATION=1 to run Docker integration tests",
)
def test_staged_repository_runs_in_analysis_container(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    tracked = source / "service.py"
    tracked.write_text("value = 1\n")
    subprocess.run(["git", "add", "service.py"], cwd=source, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "base"],
        cwd=source,
        check=True,
    )
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=source, check=True, capture_output=True, text=True
    ).stdout.strip()

    tracked.write_text("value = 2\n")
    subprocess.run(["git", "add", "service.py"], cwd=source, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "head"],
        cwd=source,
        check=True,
    )
    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=source, check=True, capture_output=True, text=True
    ).stdout.strip()

    results = run_analysis_in_container(
        str(source), "unused-for-local-fetch", base_sha, head_sha, ["service.py"]
    )

    diff = next(result for result in results if result.get("type") == "diff_stats")
    assert diff["stats"] == [{
        "file": "service.py",
        "additions": 1,
        "deletions": 1,
        "changes": 2,
        "status": "modified",
    }]


@pytest.mark.skipif(
    os.environ.get("RUN_GITHUB_PRIVATE_INTEGRATION") != "1",
    reason="set RUN_GITHUB_PRIVATE_INTEGRATION=1 to verify live private repository access",
)
def test_live_github_app_can_fetch_private_repository():
    import httpx

    from app.core.github import GITHUB_API_URL, _build_app_jwt, get_installation_token

    app_headers = {
        "Authorization": f"Bearer {_build_app_jwt()}",
        "Accept": "application/vnd.github+json",
    }
    response = httpx.get(
        f"{GITHUB_API_URL}/app/installations", headers=app_headers, timeout=30.0
    )
    response.raise_for_status()

    private_repositories = 0
    for installation in response.json():
        token = asyncio.run(get_installation_token(installation["id"]))
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        }
        repos_response = httpx.get(
            f"{GITHUB_API_URL}/installation/repositories",
            headers=headers,
            params={"per_page": 100},
            timeout=30.0,
        )
        repos_response.raise_for_status()
        for repository in repos_response.json().get("repositories", []):
            if not repository.get("private"):
                continue
            private_repositories += 1
            commits_response = httpx.get(
                f"{GITHUB_API_URL}/repos/{repository['full_name']}/commits",
                headers=headers,
                params={"per_page": 2},
                timeout=30.0,
            )
            commits_response.raise_for_status()
            commits = commits_response.json()
            if len(commits) < 2:
                continue

            commit_response = httpx.get(
                f"{GITHUB_API_URL}/repos/{repository['full_name']}/commits/{commits[0]['sha']}",
                headers=headers,
                timeout=30.0,
            )
            commit_response.raise_for_status()
            filenames = [
                file["filename"]
                for file in commit_response.json().get("files", [])
                if file.get("status") != "removed"
            ]
            if not filenames:
                continue

            results = run_analysis_in_container(
                repository["clone_url"],
                token,
                commits[1]["sha"],
                commits[0]["sha"],
                filenames,
            )
            assert any(result.get("type") == "diff_stats" for result in results)
            return

    pytest.fail(
        f"No accessible private repository with two commits was found ({private_repositories} private repositories checked)"
    )
