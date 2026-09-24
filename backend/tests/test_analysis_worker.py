import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    AnalysisJob,
    AnalyzedRepository,
    JobStatus,
    PullRequest,
    Repository,
    User,
)
from app.workers import analysis_worker


def make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def seed_job(factory, analysis_enabled):
    db = factory()
    db.add_all([
        User(id=1, github_id=10, login="octocat"),
        Repository(
            id=1,
            github_id=100,
            owner="acme",
            name="project",
            full_name="acme/project",
            installation_id=900,
            url="https://github.com/acme/project",
        ),
        PullRequest(
            id=1,
            github_id=200,
            repository_id=1,
            number=12,
            title="Improve analysis",
            state="open",
            draft=False,
            author_login="octocat",
            source_branch="feature",
            target_branch="main",
            head_sha="head-sha",
            base_sha="base-sha",
            url="https://github.com/acme/project/pull/12",
            opened_at=datetime.now(timezone.utc),
        ),
        AnalysisJob(id=1, pull_request_id=1, status=JobStatus.pending),
    ])
    if analysis_enabled:
        db.add(AnalyzedRepository(user_id=1, repository_id=1))
    db.commit()
    db.close()


def test_queued_analysis_does_not_run_after_repository_is_disabled(monkeypatch):
    factory = make_session_factory()
    seed_job(factory, analysis_enabled=False)
    monkeypatch.setattr(analysis_worker, "SessionLocal", factory)

    def must_not_run(*_args, **_kwargs):
        pytest.fail("analysis process started for a disabled repository")

    monkeypatch.setattr(analysis_worker, "run_analysis_in_container", must_not_run)

    asyncio.run(analysis_worker.analyze_pr({}, pull_request_id=1, job_id=1))

    db = factory()
    job = db.get(AnalysisJob, 1)
    assert job.status == JobStatus.failed
    assert job.error == "Repository analysis was disabled before this job started"
    assert job.finished_at is not None


def test_analysis_process_crash_marks_job_failed_and_stores_error(monkeypatch):
    factory = make_session_factory()
    seed_job(factory, analysis_enabled=True)
    monkeypatch.setattr(analysis_worker, "SessionLocal", factory)

    async def installation_token(_installation_id):
        return "token"

    def crash(*_args, **_kwargs):
        raise RuntimeError("analysis container exited unexpectedly")

    monkeypatch.setattr(analysis_worker, "get_installation_token", installation_token)
    monkeypatch.setattr(analysis_worker, "run_analysis_in_container", crash)

    with pytest.raises(RuntimeError, match="analysis container exited unexpectedly"):
        asyncio.run(analysis_worker.analyze_pr({}, pull_request_id=1, job_id=1))

    # Failure details remain available after the worker propagates the exception.
    db = factory()
    job = db.get(AnalysisJob, 1)
    assert job.status == JobStatus.failed
    assert job.error == "analysis container exited unexpectedly"
    assert job.finished_at is not None
