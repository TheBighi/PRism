import hashlib
import hmac
import os
from contextlib import asynccontextmanager
from datetime import datetime
from dotenv import load_dotenv

import httpx
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.database import get_db, engine, Base
from app.models import Repository, PullRequest, PullRequestFile, AnalysisJob
from app.auth import AuthContext, get_current_user, router as auth_router, github_repository_ids, get_http_client, close_http_client

from app.core.queue import enqueue_pr_analysis, enqueue_sync_history, get_queue
from app.routers.repos import router as repos_router

Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_http_client()
    yield
    await close_http_client()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(repos_router)
app.include_router(auth_router)

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
    installation_id = payload.get("installation", {}).get("id")

    repo = db.query(Repository).filter(Repository.github_id == repo_data["id"]).first()
    new_repo = False
    if not repo:
        repo = Repository(
            github_id=repo_data["id"],
            owner=repo_data["owner"]["login"],
            name=repo_data["name"],
            full_name=repo_data["full_name"],
            default_branch=repo_data.get("default_branch"),
            url=repo_data["html_url"],
            installation_id=installation_id,
        )
        db.add(repo)
        db.flush()
        new_repo = True

    elif installation_id is not None:
        repo.installation_id = installation_id

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

    return pr, repo.id, new_repo


def store_pr_files(pr, pr_data, repo_data, db: Session):
    files_url = pr_data["url"] + "/files"

    headers = {}
    github_token = os.environ.get("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    files: list[dict] = []
    page = 1
    while True:
        resp = httpx.get(
            files_url,
            headers=headers,
            params={"per_page": 100, "page": page},
            timeout=30.0,
        )
        resp.raise_for_status()
        batch = resp.json()
        files.extend(batch)
        if len(batch) < 100:
            break
        page += 1

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
            pr, repo_id, new_repo = await run_in_threadpool(store_pull_request, payload, db)

            queue = await get_queue()

            await enqueue_pr_analysis(queue, pr.id, db)

            if new_repo:
                await enqueue_sync_history(queue, repo_id)

            return JSONResponse(status_code=202, content={"ok": True})

    return {"ok": True}

@app.get("/jobs/{job_id}")
async def get_job_status(
    job_id: int,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(get_current_user),
):
    job = db.query(AnalysisJob).filter(AnalysisJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    repo = db.query(Repository).join(
        PullRequest, PullRequest.repository_id == Repository.id
    ).filter(PullRequest.id == job.pull_request_id).first()
    if not repo or repo.github_id not in await github_repository_ids(auth):
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
        "explanation": job.explanation,
        "explanation_status": job.explanation_status,
        "explanation_error": job.explanation_error,
        "explanation_started_at": job.explanation_started_at,
        "explanation_finished_at": job.explanation_finished_at,
    }

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="localhost", port=8000)
