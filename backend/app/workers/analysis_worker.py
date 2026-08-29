from datetime import datetime, timezone
from arq.connections import RedisSettings

from app.database import SessionLocal
from app.models import AnalysisJob, FileRiskSummary, JobStatus, PullRequest, PullRequestFile, Repository
from app.core.queue import enqueue_pr_analysis, enqueue_pr_explanation, get_queue
from app.core.risk_score import compute_risk_score

from app.core.container_runner import run_analysis_in_container

HOTSPOT_THRESHOLD = 60

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

        results = run_analysis_in_container(repo.url, pr.base_sha, pr.head_sha, filenames)

        file_risks = (
            db.query(FileRiskSummary)
            .filter(FileRiskSummary.repository_id == repo.id)
            .filter(FileRiskSummary.filename.in_(filenames))
            .all()
        )
        historical = {
            r.filename: {
                "commit_count_90d": r.commit_count_90d,
                "revert_count_90d": r.revert_count_90d,
                "risk_score": r.risk_score,
            }
            for r in file_risks
        }
        results.append({
            "type": "historical_risk",
            "files": historical,
        })

        hotspots = [
            {"filename": fn, "risk_score": d["risk_score"], "commit_count_90d": d["commit_count_90d"], "revert_count_90d": d["revert_count_90d"]}
            for fn, d in historical.items()
            if d["risk_score"] >= HOTSPOT_THRESHOLD
        ]
        results.append({
            "type": "hotspot_files",
            "files": hotspots,
        })

        results.append({
            "type": "risk_score",
            **compute_risk_score(results, filenames),
        })

        job.status = JobStatus.done
        job.results = results
        job.finished_at = datetime.now(timezone.utc)
        db.commit()

        queue = await get_queue()

        await enqueue_pr_explanation(queue, job_id)
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
    queue_name = "analysis:queue"
    max_jobs = 2
    job_timeout = 300
    redis_settings = RedisSettings(host="localhost", port=6379)