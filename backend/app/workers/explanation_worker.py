from datetime import datetime, timezone

from app.database import SessionLocal
from app.models import AnalysisJob, JobStatus, ExplanationStatus, PullRequest, PullRequestFile, Repository

from app.schemas.explanation import PRExplanation
from arq.connections import RedisSettings
from app.core.llm import build_explanation_prompt, call_llm
from app.core.github import format_check_output, post_pr_check

async def generate_explanation(ctx, job_id: int):
    db = SessionLocal()
    try:
        job = db.query(AnalysisJob).filter(AnalysisJob.id == job_id).first()
        if not job or job.status != JobStatus.done or not job.results:
            return
        job.explanation_status = ExplanationStatus.running
        job.started_at = datetime.now(timezone.utc)
        db.commit()
        prompt = build_explanation_prompt(job.results)  # truncate/select top findings by risk_score
        job.explanation = (await call_llm(prompt, PRExplanation)).model_dump(mode="json")
        job.explanation_status = ExplanationStatus.done
        job.explanation_finished_at = datetime.now(timezone.utc)
        db.commit()
        
        pr = db.query(PullRequest).filter(PullRequest.id == job.pull_request_id).first()
        repo = db.query(Repository).filter(Repository.id == pr.repository_id).first()
        if repo and repo.installation_id:
            title, summary, results_text = format_check_output(job.explanation)
            await post_pr_check(
                installation_id=repo.installation_id,
                owner=repo.owner,
                repo=repo.name,
                sha=pr.head_sha,
                title=title,
                summary=summary,
                results=results_text,
            )
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