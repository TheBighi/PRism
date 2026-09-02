import os
import time

import httpx
import jwt
from dotenv import load_dotenv

load_dotenv()

GITHUB_APP_ID = os.environ["GITHUB_APP_ID"]
GITHUB_PRIVATE_KEY_PATH = os.environ["GITHUB_PRIVATE_KEY_PATH"]
GITHUB_API_URL = "https://api.github.com"


def _read_private_key() -> str:
    with open(GITHUB_PRIVATE_KEY_PATH, "r") as f:
        return f.read()


def _build_app_jwt() -> str:
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + 9 * 60,
        "iss": GITHUB_APP_ID,
    }
    return jwt.encode(payload, _read_private_key(), algorithm="RS256")


async def get_installation_token(installation_id: int) -> str:
    app_jwt = _build_app_jwt()
    headers = {
        "Authorization": f"Bearer {app_jwt}",
        "Accept": "application/vnd.github+json",
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{GITHUB_API_URL}/app/installations/{installation_id}/access_tokens",
            headers=headers,
            timeout=30.0,
        )
    response.raise_for_status()
    return response.json()["token"]


async def create_check(
    token: str,
    owner: str,
    repo: str,
    sha: str,
    title: str,
    summary: str,
    results: str,
    conclusion: str,
):
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    payload = {
        "name": "PRism",
        "head_sha": sha,
        "status": "completed",
        "conclusion": conclusion,
        "output": {
            "title": title,
            "summary": summary,
            "text": results,
        },
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{GITHUB_API_URL}/repos/{owner}/{repo}/check-runs",
            headers=headers,
            json=payload,
            timeout=30.0,
        )
    response.raise_for_status()
    return response.json()


async def post_pr_check(
    installation_id: int,
    owner: str,
    repo: str,
    sha: str,
    title: str,
    summary: str,
    results: str,
    conclusion: str,
):
    token = await get_installation_token(installation_id)
    return await create_check(
        token=token,
        owner=owner,
        repo=repo,
        sha=sha,
        title=title,
        summary=summary,
        results=results,
        conclusion=conclusion,
    )


def format_check_output(explanation: dict) -> tuple[str, str, str, str]:
    title = "PRism Analysis"
    summary = explanation.get("summary", "")
    top_risks = explanation.get("top_risks", [])

    by_severity: dict[str, list[dict]] = {}
    for risk in top_risks:
        severity = risk.get("severity", "medium")
        by_severity.setdefault(severity, []).append(risk)

    lines = []
    for severity in ("critical", "high", "medium", "low"):
        risks = by_severity.get(severity)
        if not risks:
            continue
        lines.append(f"## {severity.title()} Risk")
        for risk in risks:
            files = f" ({', '.join(risk['files'])})" if risk.get("files") else ""
            lines.append(f"- {risk['title']}{files}: {risk['explanation']}")

    recommendation = explanation.get("recommendation", {})
    priority = recommendation.get("priority", "review")

    if recommendation.get("summary") or recommendation.get("actions"):
        lines.append("")
        lines.append(f"## Recommendation: {priority.replace('_', ' ').title()}")
        if recommendation.get("summary"):
            lines.append(recommendation["summary"])
        for action in recommendation.get("actions", []):
            lines.append(f"- {action}")

    results_text = "\n".join(lines) if lines else "No issues found."

    priority_to_conclusion = {
        "block": "failure",
        "changes_requested": "failure",
        "review": "neutral",
        "approve": "success",
    }
    conclusion = priority_to_conclusion.get(priority, "neutral")

    return (title, summary, results_text, conclusion)

