from arq.connections import ArqRedis, RedisSettings, create_pool
from sqlalchemy.orm import Session
from app.models import AnalysisJob, JobStatus

ANALYZE_PR_JOB = "analyze_pr"


async def get_queue() -> ArqRedis:
    redis = await create_pool(RedisSettings(host="localhost", port=6379))
    return redis


async def enqueue_pr_analysis(queue, pull_request_id: int, db: Session) -> AnalysisJob:
    job = AnalysisJob(pull_request_id=pull_request_id, status=JobStatus.pending)
    db.add(job)
    db.commit()
    db.refresh(job)

    await queue.enqueue_job("analyze_pr", pull_request_id, job.id)
    return job