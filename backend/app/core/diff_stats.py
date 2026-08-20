"""
app/core/diff_stats.py

Per-file line-change stats (lines added / deleted / total changed) between the
base and head commits of a PR, computed straight from `git diff`.

Unlike the other analysis modules this doesn't produce findings — it's a
summary attached to the analysis output as {"type": "diff_stats", ...}.

Output shape per file:

    {"file": str, "status": str, "additions": int, "deletions": int, "changes": int}

`status` mirrors GitHub's per-file status (added/modified/deleted/renamed/...)
so brand-new files are called out explicitly instead of just showing up as a
non-zero addition count.
"""

import subprocess
from pathlib import Path

# git's `--name-status` letter -> the GitHub-style wording we expose.
_STATUS_NAMES = {
    "A": "added",
    "M": "modified",
    "D": "deleted",
    "R": "renamed",
    "C": "copied",
    "T": "type-changed",
    "U": "unmerged",
    "X": "unknown",
    "B": "broken",
}


def _parse_name_status(raw: str) -> dict[str, str]:
    """`git diff --name-status` stdout -> {path: status}.

    Lines are `<status>\t<path>` (renames/copies have a second tab for the
    old path, but --no-renames keeps that from ever happening here).
    """
    status_by_path = {}
    for line in raw.splitlines():
        if not line:
            continue
        parts = line.split("\t", maxsplit=1)
        if len(parts) != 2:
            continue
        status_code, path = parts
        status_by_path[path] = _STATUS_NAMES.get(status_code, status_code)
    return status_by_path


def _parse_numstat(raw: str) -> list[dict]:
    """`git diff --numstat` stdout -> per-file {file, additions, deletions}.

    Each line is `<added>\t<deleted>\t<path>`. Binary files report "-"
    instead of a count (git can't count their lines), so those become 0.
    """
    stats = []
    for line in raw.splitlines():
        if not line:
            continue
        parts = line.split("\t", maxsplit=2)
        if len(parts) != 3:
            continue

        added_raw, deleted_raw, path = parts
        added = int(added_raw) if added_raw != "-" else 0
        deleted = int(deleted_raw) if deleted_raw != "-" else 0
        stats.append({
            "file": path,
            "additions": added,
            "deletions": deleted,
            "changes": added + deleted,
        })
    return stats


def diff_stats(repo_dir: Path, base_sha: str, head_sha: str, filenames: list[str]) -> list[dict]:
    """Line-change stats for the given files between base_sha and head_sha.

    Only the passed filenames are counted, so the result lines up with the
    rest of the analysis (which also scopes to the PR's changed files).
    Each file carries its diff `status` (e.g. "added" for brand-new files,
    "deleted" for removed ones) alongside the line counts. Binary files are
    reported as 0/0 since git doesn't count lines in them.

    --no-renames keeps renames looking like a delete + an add, which matches
    the numstat column layout (a real rename would print "old => new" in the
    path column and wouldn't line up with the file list the caller gave us).
    """
    if not filenames:
        return []

    name_status = subprocess.run(
        ["git", "diff", "--no-renames", "--name-status", base_sha, head_sha, "--", *filenames],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    numstat = subprocess.run(
        ["git", "diff", "--no-renames", "--numstat", base_sha, head_sha, "--", *filenames],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if name_status.returncode != 0:
        raise RuntimeError(f"git diff --name-status failed: {name_status.stderr.strip()}")
    if numstat.returncode != 0:
        raise RuntimeError(f"git diff --numstat failed: {numstat.stderr.strip()}")

    status_by_path = _parse_name_status(name_status.stdout)
    return [
        {**stat, "status": status_by_path.get(stat["file"], "modified")}
        for stat in _parse_numstat(numstat.stdout)
    ]