import subprocess

from app.core.container_runner import _prepare_repository
from app.core.risk_score import compute_risk_score
from app.core.run_analysis import _install_project_dependencies
from app.models import AnalysisJob, JobStatus
from app.routers.repos import _job_stats, _risk_total


def test_risk_total_reads_persisted_analysis_array():
    results = [
        {"type": "linting", "results": []},
        {"type": "risk_score", "total": 72.5, "breakdown": {}},
    ]

    assert _risk_total(results) == 72.5
    assert _risk_total({"total": 41}) == 41.0


def test_job_stats_aggregate_array_results():
    jobs = [
        AnalysisJob(status=JobStatus.done, results=[{"type": "risk_score", "total": 80}]),
        AnalysisJob(status=JobStatus.done, results=[{"type": "risk_score", "total": 40}]),
        AnalysisJob(status=JobStatus.failed),
    ]

    assert _job_stats(jobs) == (60.0, 1, 2, 1)


def test_failed_tests_contribute_to_risk_score():
    output = [{
        "type": "tests",
        "results": [{
            "file": "tests/test_app.py",
            "severity": "error",
            "message": "assertion failed",
        }],
    }]

    risk = compute_risk_score(output, ["src/service.py"])

    assert risk["breakdown"]["test_failure"]["contribution"] == 10
    assert risk["breakdown"]["test_failure"]["failed_tests"] == ["tests/test_app.py"]


def test_dependency_install_supports_nested_projects_and_writable_npm_cache(tmp_path, monkeypatch):
    backend = tmp_path / "backend"
    frontend = tmp_path / "frontend"
    backend.mkdir()
    frontend.mkdir()
    (backend / "requirements.txt").write_text("fastapi\n")
    (frontend / "package.json").write_text("{}\n")
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs["cwd"]))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("app.core.run_analysis.subprocess.run", fake_run)

    _install_project_dependencies(tmp_path)

    assert any(cwd == backend and "-r" in command for command, cwd in calls)
    assert any(
        cwd == frontend and command[-2:] == ["--cache", "/tmp/npm-cache"]
        for command, cwd in calls
    )


def test_authenticated_fetch_does_not_put_token_in_command_arguments(tmp_path, monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs.get("env")))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("app.core.container_runner.subprocess.run", fake_run)

    _prepare_repository(
        "https://github.com/acme/private.git",
        "installation-secret",
        "base-sha",
        "head-sha",
        tmp_path / "repo.git",
    )

    assert all("installation-secret" not in " ".join(command) for command, _env in calls)
    fetch_environments = [env for command, env in calls if "fetch" in command]
    assert fetch_environments
    assert all(env["GIT_CONFIG_VALUE_0"].startswith("Authorization: Basic ") for env in fetch_environments)
    assert all("installation-secret" not in env["GIT_CONFIG_VALUE_0"] for env in fetch_environments)


def test_prepared_repository_exposes_both_pr_commits(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    tracked = source / "app.py"
    tracked.write_text("first = 1\n")
    subprocess.run(["git", "add", "app.py"], cwd=source, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "base"],
        cwd=source,
        check=True,
    )
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=source, check=True, capture_output=True, text=True
    ).stdout.strip()
    tracked.write_text("first = 2\n")
    subprocess.run(["git", "add", "app.py"], cwd=source, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "head"],
        cwd=source,
        check=True,
    )
    head_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=source, check=True, capture_output=True, text=True
    ).stdout.strip()

    prepared = tmp_path / "prepared.git"
    _prepare_repository(str(source), "unused-for-local-fetch", base_sha, head_sha, prepared)

    for sha in (base_sha, head_sha):
        result = subprocess.run(
            ["git", "-C", str(prepared), "cat-file", "-e", f"{sha}^{{commit}}"],
            check=False,
        )
        assert result.returncode == 0
