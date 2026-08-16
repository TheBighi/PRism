import json
import subprocess
from pathlib import Path

PY_EXTENSIONS = {".py"}

BANDIT_SEVERITY_MAP = {
    "LOW": "warning",
    "MEDIUM": "warning",
    "HIGH": "error",
}

NPM_AUDIT_SEVERITY_MAP = {
    "low": "warning",
    "moderate": "warning",
    "high": "error",
    "critical": "error",
}


class SecurityScanError(Exception):
    pass


def run_bandit(repo_dir: Path, files: list[str]) -> list[dict]:
    if not files:
        return []

    result = subprocess.run(
        ["bandit", "-f", "json", *files],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    # bandit exits non-zero when it finds issues — expected, not a failure.
    if result.returncode not in (0, 1):
        raise SecurityScanError(f"bandit failed: {result.stderr.strip()}")

    try:
        raw = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as e:
        raise SecurityScanError(f"could not parse bandit output: {e}")

    normalized = []
    for item in raw.get("results", []):
        severity = BANDIT_SEVERITY_MAP.get(item.get("issue_severity", ""), "warning")
        normalized.append({
            "file": item["filename"],  # bandit echoes back the path you passed it
            "line": item.get("line_number", 0),
            "severity": severity,
            "category": "security",
            "source": "bandit",
            "message": f"[{item.get('test_id', '')}] {item.get('issue_text', '').strip()}",
        })
    return normalized


def run_npm_audit(repo_dir: Path) -> list[dict]:
    """npm audit is project-level, not per-file — only run it if there's a
    package.json to audit against."""
    if not (repo_dir / "package.json").is_file():
        return []

    result = subprocess.run(
        ["npm", "audit", "--json"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    try:
        raw = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as e:
        raise SecurityScanError(f"could not parse npm audit output: {e}")

    if "error" in raw:
        raise SecurityScanError(f"npm audit failed: {raw['error']}")

    normalized = []
    for pkg_name, vuln in raw.get("vulnerabilities", {}).items():
        severity = NPM_AUDIT_SEVERITY_MAP.get(vuln.get("severity", ""), "warning")

        titles = [v["title"] for v in vuln.get("via", []) if isinstance(v, dict)]
        message = "; ".join(titles) if titles else f"vulnerable dependency: {pkg_name}"

        normalized.append({
            "file": "package.json",
            "line": 0,
            "severity": severity,
            "category": "security",
            "source": "npm-audit",
            "message": f"[{pkg_name}] {message}",
        })
    return normalized


def scan_files(repo_dir: Path, filenames: list[str]) -> list[dict]:
    py_files = [f for f in filenames if Path(f).suffix in PY_EXTENSIONS]

    results = []
    results.extend(run_bandit(repo_dir, py_files))
    results.extend(run_npm_audit(repo_dir))
    return results