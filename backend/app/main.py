import hashlib
import hmac
import os
from datetime import datetime
from dotenv import load_dotenv

import httpx
from fastapi import FastAPI, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.database import get_db, engine, Base
from app.models import Repository, PullRequest, PullRequestFile, AnalysisJob

from app.core.queue import enqueue_pr_analysis, get_queue

Base.metadata.create_all(bind=engine)

app = FastAPI()

load_dotenv()

WEBHOOK_SECRET = os.environ["GITHUB_WEBHOOK_SECRET"]


@app.get("/")
def read_root():
    return {"Hello": "World"}


@app.get("/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Database unavailable: {e}"
        )


def parse_github_timestamp(ts):
    if ts is None:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def store_pull_request(payload, db: Session):
    repo_data = payload["repository"]
    pr_data = payload["pull_request"]

    repo = db.query(Repository).filter(Repository.github_id == repo_data["id"]).first()
    if not repo:
        repo = Repository(
            github_id=repo_data["id"],
            owner=repo_data["owner"]["login"],
            name=repo_data["name"],
            full_name=repo_data["full_name"],
            default_branch=repo_data.get("default_branch"),
            url=repo_data["html_url"],
        )
        db.add(repo)
        db.flush()

    existing = db.query(PullRequest).filter(PullRequest.github_id == pr_data["id"]).first()
    if existing:
        existing.title = pr_data["title"]
        existing.body = pr_data.get("body")
        existing.state = pr_data["state"]
        existing.draft = pr_data.get("draft", False)
        existing.source_branch = pr_data["head"]["ref"]
        existing.target_branch = pr_data["base"]["ref"]
        existing.head_sha = pr_data["head"]["sha"]
        existing.base_sha = pr_data["base"]["sha"]
        existing.url = pr_data["html_url"]
        existing.closed_at = parse_github_timestamp(pr_data.get("closed_at"))
        existing.updated_at = func.now()
        pr = existing
    else:
        pr = PullRequest(
            github_id=pr_data["id"],
            repository_id=repo.id,
            number=pr_data["number"],
            title=pr_data["title"],
            body=pr_data.get("body"),
            state=pr_data["state"],
            draft=pr_data.get("draft", False),
            author_login=pr_data["user"]["login"],
            source_branch=pr_data["head"]["ref"],
            target_branch=pr_data["base"]["ref"],
            head_sha=pr_data["head"]["sha"],
            base_sha=pr_data["base"]["sha"],
            url=pr_data["html_url"],
            opened_at=parse_github_timestamp(pr_data["created_at"]),
            closed_at=parse_github_timestamp(pr_data.get("closed_at")),
        )
        db.add(pr)

    db.flush()

    store_pr_files(pr, pr_data, repo_data, db)

    db.commit()

    return pr


def store_pr_files(pr, pr_data, repo_data, db: Session):
    files_url = pr_data["url"] + "/files"

    headers = {}
    github_token = os.environ.get("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    try:
        resp = httpx.get(files_url, headers=headers, timeout=30.0)
        resp.raise_for_status()
        files = resp.json()
    except Exception:
        return

    db.query(PullRequestFile).filter(PullRequestFile.pull_request_id == pr.id).delete()

    for f in files:
        pr_file = PullRequestFile(
            pull_request_id=pr.id,
            filename=f["filename"],
            status=f["status"],
            additions=f.get("additions", 0),
            deletions=f.get("deletions", 0),
            changes=f.get("changes", 0),
            patch=f.get("patch"),
            sha=f.get("sha"),
        )
        db.add(pr_file)


@app.post("/github/webhook")
async def github_webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.body()

    signature = request.headers.get("X-Hub-Signature-256")

    if not signature:
        raise HTTPException(
            status_code=401,
            detail="Missing webhook signature"
        )

    expected_signature = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(signature, expected_signature):
        raise HTTPException(
            status_code=401,
            detail="Invalid webhook signature"
        )

    payload = await request.json()

    event_type = request.headers.get("X-GitHub-Event")
    if event_type == "pull_request":
        action = payload.get("action")
        if action in ("opened", "synchronize", "reopened"):
            pr = store_pull_request(payload, db)

            queue = await get_queue()

            await enqueue_pr_analysis(queue, pr.id, db)

    return {"ok": True}

@app.get("/jobs/{job_id}")
def get_job_status(job_id: int, db: Session = Depends(get_db)):
    job = db.query(AnalysisJob).filter(AnalysisJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "id": job.id,
        "pull_request_id": job.pull_request_id,
        "status": job.status,
        "error": job.error,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "results": job.results,
    }

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="localhost", port=8000)
