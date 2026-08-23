from arq.connections import ArqRedis, RedisSettings, create_pool
from sqlalchemy.orm import Session
from app.models import AnalysisJob, JobStatus

_queue_pool: ArqRedis | None = None


async def get_queue() -> ArqRedis:
    global _queue_pool
    if _queue_pool is None:
        _queue_pool = await create_pool(RedisSettings(host="localhost", port=6379))
    return _queue_pool

async def enqueue_pr_analysis(queue: ArqRedis, pull_request_id: int, db: Session) -> AnalysisJob:
    job = AnalysisJob(pull_request_id=pull_request_id, status=JobStatus.pending)
    db.add(job)
    db.commit()
    db.refresh(job)

    await queue.enqueue_job("analyze_pr", pull_request_id, job.id, _queue_name="analysis:queue")
    return job

async def enqueue_pr_explanation(queue: ArqRedis, job_id: int) -> None:
    await queue.enqueue_job("generate_explanation", job_id, _queue_name="explain:queue")

    return None