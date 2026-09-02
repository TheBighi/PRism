import asyncio
import logging
import random
from datetime import datetime, timezone

import httpx
from arq import Retry
from arq.connections import RedisSettings
from google.genai import errors as genai_errors

from app.core.github import format_check_output, post_pr_check
from app.core.llm import build_explanation_prompt, call_llm
from app.database import SessionLocal
from app.models import AnalysisJob, ExplanationStatus, JobStatus, PullRequest, Repository
from app.schemas.explanation import PRExplanation

logger = logging.getLogger(__name__)

MAX_TRIES = 5
BASE_RETRY_DELAY_SECONDS = 15
MAX_RETRY_DELAY_SECONDS = 120


def _is_transient_error(error: Exception) -> bool:
    if isinstance(error, (asyncio.TimeoutError, httpx.TransportError)):
        return True
    if not isinstance(error, genai_errors.APIError):
        return False
    return error.code in {408, 429} or error.code >= 500


async def generate_explanation(ctx, job_id: int):
    db = SessionLocal()
    try:
        job = db.query(AnalysisJob).filter(AnalysisJob.id == job_id).first()
        if not job or job.status != JobStatus.done or not job.results:
            return
        job.explanation_status = ExplanationStatus.running
        job.explanation_started_at = datetime.now(timezone.utc)
        job.explanation_error = None
        db.commit()
        prompt = build_explanation_prompt(job.results)  # truncate/select top findings by risk_score
        job.explanation = (await call_llm(prompt, PRExplanation)).model_dump(mode="json")
        job.explanation_status = ExplanationStatus.done
        job.explanation_error = None
        job.explanation_finished_at = datetime.now(timezone.utc)
        db.commit()

        pr = db.query(PullRequest).filter(PullRequest.id == job.pull_request_id).first()
        if not pr:
            logger.warning("Pull request for explanation job %s no longer exists", job_id)
            return
        repo = db.query(Repository).filter(Repository.id == pr.repository_id).first()
        if repo and repo.installation_id:
            title, summary, results, conclusion = format_check_output(job.explanation)
            await post_pr_check(
                installation_id=repo.installation_id,
                owner=repo.owner,
                repo=repo.name,
                sha=pr.head_sha,
                title=title,
                summary=summary,
                results=results,
                conclusion=conclusion,
            )
    except Exception as e:
        db.rollback()
        job = db.query(AnalysisJob).filter(AnalysisJob.id == job_id).first()
        attempt = max(int(ctx.get("job_try", 1)), 1)
        error_message = str(e)[:2000]

        if _is_transient_error(e) and attempt < MAX_TRIES:
            delay = min(
                BASE_RETRY_DELAY_SECONDS * (2 ** (attempt - 1)),
                MAX_RETRY_DELAY_SECONDS,
            )
            delay += random.uniform(0, delay * 0.25)

            if job:
                job.explanation_status = ExplanationStatus.pending
                job.explanation_error = (
                    f"Temporary API error on attempt {attempt}/{MAX_TRIES}; "
                    f"retrying in {delay:.0f}s: {error_message}"
                )
                db.commit()

            logger.warning(
                "Temporary explanation error for job %s on attempt %s/%s; retrying in %.1fs: %s",
                job_id,
                attempt,
                MAX_TRIES,
                delay,
                e,
            )
            raise Retry(defer=delay) from e

        if job:
            job.explanation_status = ExplanationStatus.failed
            job.explanation_error = error_message
            job.explanation_finished_at = datetime.now(timezone.utc)
            db.commit()
        logger.exception("Explanation generation failed permanently for job %s", job_id)
        raise
    finally:
        db.close()


class WorkerSettings:
    functions = [generate_explanation]
    queue_name = "explain:queue"
    max_jobs = 5
    job_timeout = 180
    max_tries = MAX_TRIES
    redis_settings = RedisSettings(host="localhost", port=6379)
