from datetime import datetime, timezone
from pathlib import Path
import shutil
import tempfile
from arq.connections import RedisSettings

from app.database import SessionLocal
from app.models import AnalysisJob, JobStatus, PullRequest, PullRequestFile, Repository

import time

from app.core.container_runner import run_analysis_in_container, LintError

async def analyze_pr(ctx, pull_request_id: int, job_id: int):
    db = SessionLocal()
    try:
        job = db.query(AnalysisJob).filter(AnalysisJob.id == job_id).first()
        job.status = JobStatus.running
        job.started_at = datetime.now(timezone.utc)
        db.commit()

        pr = db.query(PullRequest).filter(PullRequest.id == pull_request_id).first()
        repo = db.query(Repository).filter(Repository.id == pr.repository_id).first()
        files = (
            db.query(PullRequestFile)
            .filter(PullRequestFile.pull_request_id == pr.id)
            .filter(PullRequestFile.status != "removed")
            .all()
        )
        filenames = [f.filename for f in files]

        results = run_analysis_in_container(repo.url, pr.head_sha, filenames)

        job.status = JobStatus.done
        job.results = results
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
    except (Exception, LintError) as e:
        db.rollback()
        job = db.query(AnalysisJob).filter(AnalysisJob.id == job_id).first()
        job.status = JobStatus.failed
        job.error = str(e)
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        raise
    finally:
        db.close()

class WorkerSettings:
    functions = [analyze_pr]
    redis_settings = RedisSettings(host="localhost", port=6379)