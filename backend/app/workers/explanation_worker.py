from app.database import SessionLocal
from app.models import AnalysisJob, JobStatus, ExplanationStatus, PullRequest, PullRequestFile, Repository

from arq.connections import RedisSettings

async def generate_explanation(ctx, job_id: int):
    db = SessionLocal()
    try:
        job = db.query(AnalysisJob).filter(AnalysisJob.id == job_id).first()
        if not job or job.status != JobStatus.done or not job.results:
            return
        job.explanation_status = ExplanationStatus.running
        db.commit()

        #prompt = build_explanation_prompt(job.results)  # truncate/select top findings by risk_score
        print("Generating explanation for job_id:", job_id)
        job.explanation = "explanation" #await call_llm(prompt)
        job.explanation_status = ExplanationStatus.done
        db.commit()
    except Exception as e:
        db.rollback()
        job = db.query(AnalysisJob).filter(AnalysisJob.id == job_id).first()
        if job:
            job.explanation_status = ExplanationStatus.failed
            job.explanation_error = str(e)
            db.commit()
        raise
    finally:
        db.close()

class WorkerSettings:
    functions = [generate_explanation]
    queue_name = "explain:queue"
    max_jobs = 20
    job_timeout = 60
    max_tries = 3
    redis_settings = RedisSettings(host="localhost", port=6379)