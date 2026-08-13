from datetime import datetime, timezone
from arq.connections import RedisSettings

from app.database import SessionLocal
from app.models import AnalysisJob, JobStatus

import time

async def analyze_pr(ctx, pull_request_id: int, job_id: int):
    db = SessionLocal()
    try:
        job = db.query(AnalysisJob).filter(AnalysisJob.id == job_id).first()
        print(f"Starting analysis for PR {pull_request_id} with job ID {job_id}")
        job.status = JobStatus.running
        job.started_at = datetime.now(timezone.utc)
        db.commit()

        print(f"Analyzing PR {pull_request_id}")
        time.sleep(10)
        job.status = JobStatus.done
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as e:
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