from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import (
    Repository, PullRequest, PullRequestFile,
    AnalysisJob, FileRiskSummary, JobStatus, ExplanationStatus,
)

router = APIRouter(prefix="/api", tags=["repos"])


def _repo_summary(repo: Repository, pr_count: int, open_pr_count: int,
                   avg_risk, health_score: int, hotspot_count: int) -> dict:
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
        "pr_count": pr_count,
        "open_pr_count": open_pr_count,
        "avg_risk_score": round(avg_risk, 1) if avg_risk is not None else None,
        "health_score": health_score,
        "hotspot_count": hotspot_count,
    }


def _get_repo_stats(repo_id: int, db: Session):
    pr_stats = db.query(
        func.count(PullRequest.id),
        func.count(PullRequest.id).filter(PullRequest.state == "open"),
    ).filter(PullRequest.repository_id == repo_id).one()

    avg_risk = db.query(
        func.avg(AnalysisJob.results["total"].as_float())
    ).join(PullRequest, PullRequest.id == AnalysisJob.pull_request_id).filter(
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

    return pr_stats[0], pr_stats[1], avg_risk, health_score, hotspot_count


@router.get("/repos")
def list_repos(db: Session = Depends(get_db)):
    repos = db.query(Repository).order_by(Repository.created_at.desc()).all()
    result = []
    for r in repos:
        pr_count, open_pr, avg_risk, health, hot = _get_repo_stats(r.id, db)
        result.append(_repo_summary(r, pr_count, open_pr, avg_risk, health, hot))
    return result


@router.get("/repos/{repo_id}")
def get_repo(repo_id: int, db: Session = Depends(get_db)):
    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    pr_count, open_pr, avg_risk, health, hot = _get_repo_stats(repo_id, db)
    return _repo_summary(repo, pr_count, open_pr, avg_risk, health, hot)


@router.get("/repos/{repo_id}/health")
def get_repo_health(repo_id: int, db: Session = Depends(get_db)):
    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    job_stats = db.query(
        func.avg(AnalysisJob.results["total"].as_float()),
        func.count(AnalysisJob.id).filter(AnalysisJob.status == JobStatus.failed),
        func.count(AnalysisJob.id).filter(AnalysisJob.status == JobStatus.done),
        func.count(AnalysisJob.id).filter(
            AnalysisJob.status == JobStatus.done,
            AnalysisJob.results["total"].as_float() >= 70,
        ),
    ).join(PullRequest, PullRequest.id == AnalysisJob.pull_request_id).filter(
        PullRequest.repository_id == repo_id,
    ).one()

    pr_stats = db.query(
        func.count(PullRequest.id),
        func.count(PullRequest.id).filter(PullRequest.state == "open"),
        func.count(PullRequest.id).filter(PullRequest.state == "merged"),
    ).filter(PullRequest.repository_id == repo_id).one()

    health_score = 100
    if job_stats[0] is not None:
        health_score = max(0, min(100, 100 - int(job_stats[0])))

    hotspots = db.query(FileRiskSummary).filter(
        FileRiskSummary.repository_id == repo_id,
        FileRiskSummary.risk_score >= 60,
    ).order_by(FileRiskSummary.risk_score.desc()).limit(10).all()

    return {
        "health_score": health_score,
        "avg_risk_score": round(job_stats[0], 1) if job_stats[0] is not None else None,
        "total_prs": pr_stats[0],
        "open_prs": pr_stats[1],
        "merged_prs": pr_stats[2],
        "failed_jobs": job_stats[1],
        "done_jobs": job_stats[2],
        "high_risk_prs": job_stats[3],
        "hotspot_files": [
            {"filename": h.filename, "risk_score": h.risk_score,
             "commit_count_90d": h.commit_count_90d, "revert_count_90d": h.revert_count_90d}
            for h in hotspots
        ],
    }


@router.get("/repos/{repo_id}/pull-requests")
def list_pull_requests(repo_id: int, db: Session = Depends(get_db)):
    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    prs = db.query(PullRequest).filter(
        PullRequest.repository_id == repo_id
    ).order_by(PullRequest.opened_at.desc()).all()

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
        func.count(PullRequestFile.id),
        func.coalesce(func.sum(PullRequestFile.additions), 0),
        func.coalesce(func.sum(PullRequestFile.deletions), 0),
    ).filter(
        PullRequestFile.pull_request_id.in_(pr_ids),
    ).group_by(PullRequestFile.pull_request_id).all()

    file_map = {fs[0]: fs for fs in file_stats}

    return [
        {
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
            "risk_score": (
                latest_per_pr[pr.id].results.get("total")
                if pr.id in latest_per_pr
                and latest_per_pr[pr.id].results
                and isinstance(latest_per_pr[pr.id].results, dict)
                else None
            ),
            "job_status": (
                latest_per_pr[pr.id].status.value
                if pr.id in latest_per_pr else None
            ),
            "file_count": file_map[pr.id][1] if pr.id in file_map else 0,
            "additions": int(file_map[pr.id][2]) if pr.id in file_map else 0,
            "deletions": int(file_map[pr.id][3]) if pr.id in file_map else 0,
        }
        for pr in prs
    ]


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

    jobs = db.query(AnalysisJob).filter(
        AnalysisJob.pull_request_id == pr.id
    ).order_by(AnalysisJob.created_at.desc()).all()

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
            {"id": f.id, "filename": f.filename, "status": f.status,
             "additions": f.additions, "deletions": f.deletions, "changes": f.changes}
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

    hotspots = db.query(FileRiskSummary).filter(
        FileRiskSummary.repository_id == repo_id
    ).order_by(FileRiskSummary.risk_score.desc()).all()

    return [
        {"id": h.id, "filename": h.filename,
         "commit_count_90d": h.commit_count_90d, "revert_count_90d": h.revert_count_90d,
         "risk_score": h.risk_score,
         "computed_at": h.computed_at.isoformat() if h.computed_at else None}
        for h in hotspots
    ]


# --- Merged endpoint: single call for entire repo detail page ---

@router.get("/repos/{repo_id}/detail")
def get_repo_detail(repo_id: int, db: Session = Depends(get_db)):
    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    # --- Repo stats (1 query) ---
    pr_count, open_pr, avg_risk, health, hot = _get_repo_stats(repo_id, db)

    # --- Health detail (1 query) ---
    job_stats = db.query(
        func.avg(AnalysisJob.results["total"].as_float()),
        func.count(AnalysisJob.id).filter(AnalysisJob.status == JobStatus.failed),
        func.count(AnalysisJob.id).filter(AnalysisJob.status == JobStatus.done),
        func.count(AnalysisJob.id).filter(
            AnalysisJob.status == JobStatus.done,
            AnalysisJob.results["total"].as_float() >= 70,
        ),
    ).join(PullRequest, PullRequest.id == AnalysisJob.pull_request_id).filter(
        PullRequest.repository_id == repo_id,
    ).one()

    merged_prs = db.query(func.count(PullRequest.id)).filter(
        PullRequest.repository_id == repo_id, PullRequest.state == "merged"
    ).scalar()

    # --- PRs + jobs + files in 3 queries ---
    prs = db.query(PullRequest).filter(
        PullRequest.repository_id == repo_id
    ).order_by(PullRequest.opened_at.desc()).all()

    pr_ids = [pr.id for pr in prs]

    latest_jobs = db.query(AnalysisJob).filter(
        AnalysisJob.pull_request_id.in_(pr_ids),
    ).order_by(AnalysisJob.created_at.desc()).all() if pr_ids else []

    seen = set()
    latest_per_pr = {}
    for j in latest_jobs:
        if j.pull_request_id not in seen:
            latest_per_pr[j.pull_request_id] = j
            seen.add(j.pull_request_id)

    file_stats = db.query(
        PullRequestFile.pull_request_id,
        func.count(PullRequestFile.id),
        func.coalesce(func.sum(PullRequestFile.additions), 0),
        func.coalesce(func.sum(PullRequestFile.deletions), 0),
    ).filter(
        PullRequestFile.pull_request_id.in_(pr_ids),
    ).group_by(PullRequestFile.pull_request_id).all() if pr_ids else []

    file_map = {fs[0]: fs for fs in file_stats}

    pr_list = [
        {
            "id": pr.id,
            "number": pr.number,
            "title": pr.title,
            "state": pr.state,
            "draft": pr.draft,
            "author_login": pr.author_login,
            "source_branch": pr.source_branch,
            "target_branch": pr.target_branch,
            "url": pr.url,
            "opened_at": pr.opened_at.isoformat() if pr.opened_at else None,
            "risk_score": (
                latest_per_pr[pr.id].results.get("total")
                if pr.id in latest_per_pr
                and latest_per_pr[pr.id].results
                and isinstance(latest_per_pr[pr.id].results, dict)
                else None
            ),
            "job_status": (
                latest_per_pr[pr.id].status.value
                if pr.id in latest_per_pr else None
            ),
            "file_count": file_map[pr.id][1] if pr.id in file_map else 0,
            "additions": int(file_map[pr.id][2]) if pr.id in file_map else 0,
            "deletions": int(file_map[pr.id][3]) if pr.id in file_map else 0,
        }
        for pr in prs
    ]

    # --- Hotspots (1 query) ---
    hotspots = db.query(FileRiskSummary).filter(
        FileRiskSummary.repository_id == repo_id,
        FileRiskSummary.risk_score >= 60,
    ).order_by(FileRiskSummary.risk_score.desc()).limit(10).all()

    return {
        "repo": _repo_summary(repo, pr_count, open_pr, avg_risk, health, hot),
        "health": {
            "health_score": health,
            "avg_risk_score": round(avg_risk, 1) if avg_risk is not None else None,
            "total_prs": pr_count,
            "open_prs": open_pr,
            "merged_prs": merged_prs,
            "failed_jobs": job_stats[1],
            "done_jobs": job_stats[2],
            "high_risk_prs": job_stats[3],
            "hotspot_files": [
                {"filename": h.filename, "risk_score": h.risk_score,
                 "commit_count_90d": h.commit_count_90d, "revert_count_90d": h.revert_count_90d}
                for h in hotspots
            ],
        },
        "pull_requests": pr_list,
        "hotspots": [
            {"id": h.id, "filename": h.filename,
             "commit_count_90d": h.commit_count_90d, "revert_count_90d": h.revert_count_90d,
             "risk_score": h.risk_score}
            for h in db.query(FileRiskSummary).filter(
                FileRiskSummary.repository_id == repo_id
            ).order_by(FileRiskSummary.risk_score.desc()).all()
        ],
    }
