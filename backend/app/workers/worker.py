from datetime import datetime, timezone
from pathlib import Path
import shutil
import tempfile
from arq.connections import RedisSettings

from app.database import SessionLocal
from app.models import AnalysisJob, JobStatus, PullRequest, PullRequestFile, Repository
from app.core.linting import clone_repo_at_sha, LintError, lint_files
from app.core.security_scan import scan_files, SecurityScanError

import time

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

        tmp_dir = Path(tempfile.mkdtemp(prefix="pr-analysis-"))
        try:
            clone_repo_at_sha(repo.url, pr.head_sha, tmp_dir)

            results = []
            results.extend(lint_files(tmp_dir, filenames))
            results.extend(scan_files(tmp_dir, filenames))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        job.status = JobStatus.done
        job.results = results
        print(f"Analysis results for PR {pull_request_id}: {results}")
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
    except (Exception, LintError, SecurityScanError) as e:
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