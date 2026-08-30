from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, select, literal_column

from app.database import get_db
from app.models import (
    Repository, PullRequest, PullRequestFile,
    AnalysisJob, FileRiskSummary, JobStatus, ExplanationStatus,
)

router = APIRouter(prefix="/api", tags=["repos"])


def _repo_summary(repo: Repository, stats: dict) -> dict:
    return {
        "id": repo.id,
        "github_id": repo.github_id,
        "owner": repo.owner,
        "name": repo.name,
        "full_name": repo.full_name,
        "default_branch": repo.default_branch,
        "url": repo.url,
        "created_at": repo.created_at.isoformat() if repo.created_at else None,
        "history_last_synced_at": repo.history_last_synced_at.isoformat() if repo.history_last_synced_at else None,
        "pr_count": stats["pr_count"],
        "open_pr_count": stats["open_pr_count"],
        "avg_risk_score": round(stats["avg_risk"], 1) if stats["avg_risk"] is not None else None,
        "health_score": stats["health_score"],
        "hotspot_count": stats["hotspot_count"],
    }


def _get_repo_stats(repo_id: int, db: Session) -> dict:
    pr_stats = db.query(
        func.count(PullRequest.id).label("pr_count"),
        func.count(PullRequest.id).filter(PullRequest.state == "open").label("open_pr_count"),
    ).filter(PullRequest.repository_id == repo_id).one()

    avg_risk = db.query(
        func.avg(AnalysisJob.results["total"].as_float())
    ).join(
        PullRequest, PullRequest.id == AnalysisJob.pull_request_id
    ).filter(
        PullRequest.repository_id == repo_id,
        AnalysisJob.status == JobStatus.done,
        AnalysisJob.results.isnot(None),
    ).scalar()

    hotspot_count = db.query(func.count(FileRiskSummary.id)).filter(
        FileRiskSummary.repository_id == repo_id,
        FileRiskSummary.risk_score >= 60,
    ).scalar()

    health_score = 100
    if avg_risk is not None:
        health_score = max(0, min(100, 100 - int(avg_risk)))

    return {
        "pr_count": pr_stats.pr_count,
        "open_pr_count": pr_stats.open_pr_count,
        "avg_risk": avg_risk,
        "health_score": health_score,
        "hotspot_count": hotspot_count,
    }


@router.get("/repos")
def list_repos(db: Session = Depends(get_db)):
    repos = db.query(Repository).order_by(Repository.created_at.desc()).all()
    return [_repo_summary(r, _get_repo_stats(r.id, db)) for r in repos]


@router.get("/repos/{repo_id}")
def get_repo(repo_id: int, db: Session = Depends(get_db)):
    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    return _repo_summary(repo, _get_repo_stats(repo_id, db))


@router.get("/repos/{repo_id}/health")
def get_repo_health(repo_id: int, db: Session = Depends(get_db)):
    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    job_stats = db.query(
        func.avg(AnalysisJob.results["total"].as_float()).label("avg_risk"),
        func.count(AnalysisJob.id).filter(AnalysisJob.status == JobStatus.failed).label("failed"),
        func.count(AnalysisJob.id).filter(AnalysisJob.status == JobStatus.done).label("done"),
        func.count(AnalysisJob.id).filter(
            AnalysisJob.status == JobStatus.done,
            AnalysisJob.results["total"].as_float() >= 70,
        ).label("high_risk"),
    ).join(
        PullRequest, PullRequest.id == AnalysisJob.pull_request_id
    ).filter(
        PullRequest.repository_id == repo_id,
    ).one()

    pr_stats = db.query(
        func.count(PullRequest.id).label("total"),
        func.count(PullRequest.id).filter(PullRequest.state == "open").label("open"),
        func.count(PullRequest.id).filter(PullRequest.state == "merged").label("merged"),
    ).filter(PullRequest.repository_id == repo_id).one()

    health_score = 100
    if job_stats.avg_risk is not None:
        health_score = max(0, min(100, 100 - int(job_stats.avg_risk)))

    hotspot_files = db.query(FileRiskSummary).filter(
        FileRiskSummary.repository_id == repo_id,
        FileRiskSummary.risk_score >= 60,
    ).order_by(FileRiskSummary.risk_score.desc()).limit(10).all()

    return {
        "health_score": health_score,
        "avg_risk_score": round(job_stats.avg_risk, 1) if job_stats.avg_risk is not None else None,
        "total_prs": pr_stats.total,
        "open_prs": pr_stats.open,
        "merged_prs": pr_stats.merged,
        "failed_jobs": job_stats.failed,
        "done_jobs": job_stats.done,
        "high_risk_prs": job_stats.high_risk,
        "hotspot_files": [
            {
                "filename": h.filename,
                "risk_score": h.risk_score,
                "commit_count_90d": h.commit_count_90d,
                "revert_count_90d": h.revert_count_90d,
            }
            for h in hotspot_files
        ],
    }


@router.get("/repos/{repo_id}/pull-requests")
def list_pull_requests(repo_id: int, db: Session = Depends(get_db)):
    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    prs = (
        db.query(PullRequest)
        .filter(PullRequest.repository_id == repo_id)
        .order_by(PullRequest.opened_at.desc())
        .all()
    )

    if not prs:
        return []

    pr_ids = [pr.id for pr in prs]

    latest_jobs = db.query(AnalysisJob).filter(
        AnalysisJob.pull_request_id.in_(pr_ids),
    ).order_by(AnalysisJob.created_at.desc()).all()

    seen = set()
    latest_per_pr = {}
    for j in latest_jobs:
        if j.pull_request_id not in seen:
            latest_per_pr[j.pull_request_id] = j
            seen.add(j.pull_request_id)

    file_stats = db.query(
        PullRequestFile.pull_request_id,
        func.count(PullRequestFile.id).label("file_count"),
        func.coalesce(func.sum(PullRequestFile.additions), 0).label("additions"),
        func.coalesce(func.sum(PullRequestFile.deletions), 0).label("deletions"),
    ).filter(
        PullRequestFile.pull_request_id.in_(pr_ids),
    ).group_by(PullRequestFile.pull_request_id).all()

    file_map = {fs.pull_request_id: fs for fs in file_stats}

    result = []
    for pr in prs:
        latest_job = latest_per_pr.get(pr.id)
        risk_score = None
        job_status = None

        if latest_job:
            job_status = latest_job.status.value if isinstance(latest_job.status, JobStatus) else latest_job.status
            if latest_job.results and isinstance(latest_job.results, dict):
                risk_score = latest_job.results.get("total")

        fs = file_map.get(pr.id)
        result.append({
            "id": pr.id,
            "github_id": pr.github_id,
            "number": pr.number,
            "title": pr.title,
            "state": pr.state,
            "draft": pr.draft,
            "author_login": pr.author_login,
            "source_branch": pr.source_branch,
            "target_branch": pr.target_branch,
            "url": pr.url,
            "opened_at": pr.opened_at.isoformat() if pr.opened_at else None,
            "closed_at": pr.closed_at.isoformat() if pr.closed_at else None,
            "risk_score": risk_score,
            "job_status": job_status,
            "file_count": fs.file_count if fs else 0,
            "additions": int(fs.additions) if fs else 0,
            "deletions": int(fs.deletions) if fs else 0,
        })

    return result


@router.get("/repos/{repo_id}/pull-requests/{pr_number}")
def get_pull_request(repo_id: int, pr_number: int, db: Session = Depends(get_db)):
    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    pr = db.query(PullRequest).filter(
        PullRequest.number == pr_number,
        PullRequest.repository_id == repo_id,
    ).first()
    if not pr:
        raise HTTPException(status_code=404, detail="Pull request not found")

    files = db.query(PullRequestFile).filter(
        PullRequestFile.pull_request_id == pr.id
    ).all()

    jobs = (
        db.query(AnalysisJob)
        .filter(AnalysisJob.pull_request_id == pr.id)
        .order_by(AnalysisJob.created_at.desc())
        .all()
    )

    return {
        "id": pr.id,
        "github_id": pr.github_id,
        "number": pr.number,
        "title": pr.title,
        "body": pr.body,
        "state": pr.state,
        "draft": pr.draft,
        "author_login": pr.author_login,
        "source_branch": pr.source_branch,
        "target_branch": pr.target_branch,
        "head_sha": pr.head_sha,
        "base_sha": pr.base_sha,
        "url": pr.url,
        "opened_at": pr.opened_at.isoformat() if pr.opened_at else None,
        "closed_at": pr.closed_at.isoformat() if pr.closed_at else None,
        "files": [
            {
                "id": f.id,
                "filename": f.filename,
                "status": f.status,
                "additions": f.additions,
                "deletions": f.deletions,
                "changes": f.changes,
            }
            for f in files
        ],
        "jobs": [
            {
                "id": j.id,
                "status": j.status.value if isinstance(j.status, JobStatus) else j.status,
                "error": j.error,
                "created_at": j.created_at.isoformat() if j.created_at else None,
                "started_at": j.started_at.isoformat() if j.started_at else None,
                "finished_at": j.finished_at.isoformat() if j.finished_at else None,
                "results": j.results,
                "explanation": j.explanation,
                "explanation_status": j.explanation_status.value if isinstance(j.explanation_status, ExplanationStatus) else j.explanation_status,
            }
            for j in jobs
        ],
    }


@router.get("/repos/{repo_id}/hotspots")
def get_hotspots(repo_id: int, db: Session = Depends(get_db)):
    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    hotspots = (
        db.query(FileRiskSummary)
        .filter(FileRiskSummary.repository_id == repo_id)
        .order_by(FileRiskSummary.risk_score.desc())
        .all()
    )

    return [
        {
            "id": h.id,
            "filename": h.filename,
            "commit_count_90d": h.commit_count_90d,
            "revert_count_90d": h.revert_count_90d,
            "risk_score": h.risk_score,
            "computed_at": h.computed_at.isoformat() if h.computed_at else None,
        }
        for h in hotspots
    ]
