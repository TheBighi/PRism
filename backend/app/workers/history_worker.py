from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv
from sqlalchemy import func

load_dotenv()

from arq.connections import RedisSettings

from app.core.github import get_installation_token
from app.database import SessionLocal
from app.models import Commit, CommitFile, FileRiskSummary, Repository

GITHUB_API_URL = "https://api.github.com"


async def _fetch_commits(token: str, owner: str, repo: str, since: str | None) -> list[dict]:
    commits = []
    url = f"{GITHUB_API_URL}/repos/{owner}/{repo}/commits"
    params = {"per_page": 100}
    if since:
        params["since"] = since

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    async with httpx.AsyncClient() as client:
        while url:
            response = await client.get(url, headers=headers, params=params, timeout=30.0)
            response.raise_for_status()
            commits.extend(response.json())
            url = response.links.get("next", {}).get("url")
            params = {}

    return commits


async def _fetch_commit_detail(token: str, owner: str, repo: str, sha: str) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{GITHUB_API_URL}/repos/{owner}/{repo}/commits/{sha}",
            headers=headers,
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()


def _is_revert(message: str) -> bool:
    return message.startswith("Revert") and "This reverts commit" in message


COMMIT_COUNT_CAP = 20
REVERT_RATIO_CAP = 0.4


def compute_file_risk_scores(db, repository_id: int):
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)

    revert_count_col = func.count(Commit.id).filter(Commit.is_revert == True)

    rows = (
        db.query(
            CommitFile.filename,
            func.count(Commit.id).label("commit_count"),
            revert_count_col.label("revert_count"),
        )
        .join(Commit, CommitFile.commit_id == Commit.id)
        .filter(Commit.repository_id == repository_id)
        .filter(Commit.committed_at >= cutoff)
        .group_by(CommitFile.filename)
        .all()
    )

    db.query(FileRiskSummary).filter(FileRiskSummary.repository_id == repository_id).delete()

    for filename, commit_count, revert_count in rows:
        commit_count = int(commit_count)
        revert_count = int(revert_count)

        freq_score = min(commit_count / COMMIT_COUNT_CAP, 1.0)
        revert_ratio = revert_count / commit_count if commit_count > 0 else 0.0
        revert_score = min(revert_ratio / REVERT_RATIO_CAP, 1.0)

        risk_score = int(round((freq_score * 0.6 + revert_score * 0.4) * 100))

        db.add(FileRiskSummary(
            repository_id=repository_id,
            filename=filename,
            commit_count_90d=commit_count,
            revert_count_90d=revert_count,
            risk_score=risk_score,
            computed_at=datetime.now(timezone.utc),
        ))

    db.flush()


async def sync_history(ctx, repository_id: int):
    db = SessionLocal()
    try:
        repo = db.query(Repository).filter(Repository.id == repository_id).first()
        if not repo or not repo.installation_id:
            return

        token = await get_installation_token(repo.installation_id)

        since = None
        if repo.history_last_synced_at:
            since = repo.history_last_synced_at.isoformat()

        raw_commits = await _fetch_commits(token, repo.owner, repo.name, since)

        for raw in raw_commits:
            sha = raw["sha"]
            if db.query(Commit).filter(Commit.sha == sha).first():
                continue

            detail = await _fetch_commit_detail(token, repo.owner, repo.name, sha)

            commit_info = detail["commit"]
            author_login = raw.get("author", {}).get("login") if raw.get("author") else None
            message = commit_info.get("message", "")
            date_str = (
                commit_info.get("author", {}).get("date")
                or commit_info.get("committer", {}).get("date")
            )
            committed_at = datetime.fromisoformat(date_str.replace("Z", "+00:00"))

            commit = Commit(
                repository_id=repo.id,
                sha=sha,
                author_login=author_login,
                committed_at=committed_at,
                message=message,
                is_revert=_is_revert(message),
            )
            db.add(commit)
            db.flush()

            total_additions = 0
            total_deletions = 0

            for f in detail.get("files", []):
                additions = f.get("additions", 0)
                deletions = f.get("deletions", 0)
                total_additions += additions
                total_deletions += deletions

                db.add(CommitFile(
                    commit_id=commit.id,
                    filename=f["filename"],
                    status=f["status"],
                    additions=additions,
                    deletions=deletions,
                    changes=f.get("changes", 0),
                ))

            commit.additions = total_additions
            commit.deletions = total_deletions

        repo.history_last_synced_at = datetime.now(timezone.utc)
        db.flush()

        compute_file_risk_scores(db, repository_id)

        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


class WorkerSettings:
    functions = [sync_history]
    queue_name = "history:queue"
    max_jobs = 5
    job_timeout = 600
    max_tries = 3
    redis_settings = RedisSettings(host="localhost", port=6379)
