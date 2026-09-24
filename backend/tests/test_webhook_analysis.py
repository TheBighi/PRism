import asyncio
import hashlib
import hmac
import json
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.database import Base
from app.models import (
    AnalysisJob,
    AnalyzedRepository,
    JobStatus,
    PullRequestFile,
    Repository,
    User,
)


@compiles(BigInteger, "sqlite")
def compile_big_integer_as_integer(_type, _compiler, **_kwargs):
    # SQLite only auto-increments columns declared with the exact INTEGER type.
    return "INTEGER"


def make_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def pull_request_payload(head_sha="head-sha"):
    return {
        "action": "opened",
        "installation": {"id": 900},
        "repository": {
            "id": 100,
            "name": "project",
            "full_name": "acme/project",
            "owner": {"login": "acme"},
            "html_url": "https://github.com/acme/project",
            "default_branch": "main",
        },
        "pull_request": {
            "id": 200,
            "number": 12,
            "title": "Improve analysis",
            "body": None,
            "state": "open",
            "draft": False,
            "merged": False,
            "user": {"login": "octocat"},
            "head": {"ref": "feature", "sha": head_sha},
            "base": {"ref": "main", "sha": "base-sha"},
            "html_url": "https://github.com/acme/project/pull/12",
            "url": "https://api.github.com/repos/acme/project/pulls/12",
            "created_at": "2026-01-01T00:00:00Z",
            "closed_at": None,
        },
    }


class FakeRequest:
    def __init__(self, payload):
        self._payload = payload
        self._body = json.dumps(payload).encode()
        signature = hmac.new(
            main.WEBHOOK_SECRET.encode(), self._body, hashlib.sha256
        ).hexdigest()
        self.headers = {
            "X-Hub-Signature-256": f"sha256={signature}",
            "X-GitHub-Event": "pull_request",
        }

    async def body(self):
        return self._body

    async def json(self):
        return self._payload


class FakeResponse:
    def __init__(self, files):
        self._files = files

    def raise_for_status(self):
        return None

    def json(self):
        return self._files


def test_duplicate_pull_request_webhook_creates_only_one_analysis_job(monkeypatch):
    db = make_db()
    user = User(id=1, github_id=1, login="octocat")
    repo = Repository(
        id=1,
        github_id=100,
        owner="acme",
        name="project",
        full_name="acme/project",
        installation_id=900,
    )
    db.add_all([user, repo, AnalyzedRepository(user_id=1, repository_id=1)])
    db.commit()

    async def inline(func, *args):
        return func(*args)

    async def installation_token(_installation_id):
        return "token"

    async def fake_enqueue(_queue, pull_request_id, session):
        # Persist jobs in the test DB so duplicate-delivery behavior is observable.
        job = AnalysisJob(id=1, pull_request_id=pull_request_id, status=JobStatus.pending)
        session.add(job)
        session.commit()
        return job

    async def no_history_sync(_queue, _repository_id):
        return None

    monkeypatch.setattr(main, "run_in_threadpool", inline)
    monkeypatch.setattr(main, "get_installation_token", installation_token)
    monkeypatch.setattr(main, "get_queue", lambda: asyncio.sleep(0, result=object()))
    monkeypatch.setattr(main, "enqueue_pr_analysis", fake_enqueue)
    monkeypatch.setattr(main, "enqueue_sync_history", no_history_sync)
    monkeypatch.setattr(main.httpx, "get", lambda *args, **kwargs: FakeResponse([]))

    request = FakeRequest(pull_request_payload())
    asyncio.run(main.github_webhook(request, db))
    asyncio.run(main.github_webhook(request, db))

    assert db.query(AnalysisJob).count() == 1


def test_pull_request_update_removes_files_no_longer_in_pr(monkeypatch):
    db = make_db()
    payload = pull_request_payload()
    responses = iter([
        FakeResponse([
            {"filename": "src/kept.py", "status": "modified"},
            {"filename": "src/removed.py", "status": "modified"},
        ]),
        FakeResponse([
            {"filename": "src/kept.py", "status": "modified"},
        ]),
    ])
    monkeypatch.setattr(main.httpx, "get", lambda *args, **kwargs: next(responses))

    pr, _ = main.store_pull_request(payload, db, github_token="token")
    payload["action"] = "synchronize"
    payload["pull_request"]["head"]["sha"] = "new-head-sha"
    main.store_pull_request(payload, db, github_token="token")

    # The stored list mirrors GitHub's latest snapshot rather than accumulating rows.
    files = db.query(PullRequestFile).filter_by(pull_request_id=pr.id).all()
    assert [file.filename for file in files] == ["src/kept.py"]
