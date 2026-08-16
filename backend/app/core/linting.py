"""
app/core/linting.py

Clones a PR's head commit, runs Ruff (Python) and ESLint (JS/TS) against the
changed files, and normalizes results into:

    {file, line, severity, category, source, message}
"""

from curses import raw
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable

PY_EXTENSIONS = {".py"}
JS_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx"}

# Ruff codes are like "E501", "F401" — first letter-ish prefix is a decent
# proxy for category. Adjust to taste.
RUFF_CATEGORY_MAP = {
    "E": "style",
    "W": "style",
    "F": "logic",
    "B": "bug-risk",
    "C": "complexity",
    "N": "naming",
    "S": "security",
    "I": "imports",
}


class LintError(Exception):
    pass


def clone_repo_at_sha(clone_url: str, sha: str, dest: Path) -> None:
    """Shallow-fetch a single commit into `dest`."""
    subprocess.run(
        ["git", "init", "-q", str(dest)],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(dest), "fetch", "-q", "--depth", "1", clone_url, sha],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(dest), "checkout", "-q", "FETCH_HEAD"],
        check=True,
    )


def _filter_existing(repo_dir: Path, filenames: Iterable[str]) -> list[str]:
    """Only lint files that actually exist post-checkout (skip deleted ones)."""
    return [f for f in filenames if (repo_dir / f).is_file()]


def run_ruff(repo_dir: Path, files: list[str]) -> list[dict]:
    if not files:
        return []

    result = subprocess.run(
        ["ruff", "check", "--output-format=json", *files],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    # ruff exits non-zero when it finds lint errors — that's expected, not a failure.
    if result.returncode not in (0, 1):
        raise LintError(f"ruff failed: {result.stderr.strip()}")

    try:
        raw = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as e:
        raise LintError(f"could not parse ruff output: {e}")

    normalized = []
    for item in raw:
        code = item.get("code") or ""
        rel_path = Path(item["filename"]).relative_to(repo_dir).as_posix()

        if code == "invalid-syntax":
            severity = "error"
            category = "syntax"
        else:
            severity = "error" if code.startswith("F") else "warning"
            category = RUFF_CATEGORY_MAP.get(code[:1], "other")

        normalized.append({
            "file": rel_path,
            "line": item["location"]["row"],
            "severity": severity,
            "category": category,
            "source": "ruff",
            "message": f"[{code}] {item['message']}",
        })
    return normalized


def run_eslint(repo_dir: Path, files: list[str]) -> list[dict]:
    if not files:
        return []

    result = subprocess.run(
        ["npx", "--yes", "eslint", "--format=json", *files],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    # eslint also exits non-zero on lint findings.
    if result.returncode not in (0, 1):
        raise LintError(f"eslint failed: {result.stderr.strip()}")

    try:
        raw = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as e:
        raise LintError(f"could not parse eslint output: {e}")

    severity_map = {1: "warning", 2: "error"}

    normalized = []
    for file_result in raw:
        rel_path = Path(file_result["filePath"]).relative_to(repo_dir).as_posix()
        for msg in file_result.get("messages", []):
            normalized.append({
                "file": rel_path,
                "line": msg.get("line", 0),
                "severity": severity_map.get(msg.get("severity"), "warning"),
                "category": "lint" if msg.get("ruleId") else "syntax",
                "source": "eslint",
                "message": f"[{msg.get('ruleId', 'parse-error')}] {msg['message']}",
            })
    return normalized


def lint_files(repo_dir: Path, filenames: list[str]) -> list[dict]:
    existing = _filter_existing(repo_dir, filenames)
    py_files = [f for f in existing if Path(f).suffix in PY_EXTENSIONS]
    js_files = [f for f in existing if Path(f).suffix in JS_EXTENSIONS]

    results = []
    results.extend(run_ruff(repo_dir, py_files))
    results.extend(run_eslint(repo_dir, js_files))
    return results