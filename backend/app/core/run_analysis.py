import json
import sys
import shutil
import subprocess
import tempfile
from pathlib import Path

from dependency_diff import (
    DependencyDiffError,
    dependency_state,
    diff_dependencies,
    normalize_dependency_changes,
)
from linting import clone_repo_at_sha, lint_files, LintError
from security_scan import scan_files, SecurityScanError
from type_check import type_check_files, new_errors, TypeCheckError


def _checkout(repo_dir: Path, clone_url: str, sha: str):
    try:
        subprocess.run(["git", "fetch", "--depth", "1", clone_url, sha],
                        cwd=repo_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "checkout", "FETCH_HEAD"],
                        cwd=repo_dir, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise LintError(f"git checkout of {sha} failed: {e.stderr.strip()}") from e


def _normalize_type_errors(errors):
    return [
        {
            "file": e.file,
            "line": e.line,
            "column": e.column,
            "severity": "error",
            "category": "types",
            "source": e.tool,
            "message": f"[{e.code}] {e.message}" if e.code else e.message,
        }
        for e in errors
    ]


def _clean_path(f: str) -> str:
    """Normalize a tool-reported path to a repo-relative posix path."""
    return Path(f).as_posix().removeprefix("./")


def main():
    if len(sys.argv) < 4:
        print("usage: run_analysis.py <clone_url> <base_sha> <head_sha> [files...]", file=sys.stderr)
        sys.exit(2)

    clone_url, base_sha, head_sha, *filenames = sys.argv[1:]

    tmp_dir = Path(tempfile.mkdtemp(prefix="pr-analysis-"))
    try:
        clone_repo_at_sha(clone_url, head_sha, tmp_dir)

        results = []
        results.extend(lint_files(tmp_dir, filenames))
        results.extend(scan_files(tmp_dir, filenames))

        head_type_errors = type_check_files(tmp_dir, filenames)
        head_deps = dependency_state(tmp_dir)
        _checkout(tmp_dir, clone_url, base_sha)
        base_type_errors = type_check_files(tmp_dir, filenames)
        base_deps = dependency_state(tmp_dir)
        _checkout(tmp_dir, clone_url, head_sha)  # restore for anything downstream

        results.extend(_normalize_type_errors(new_errors(head_type_errors, base_type_errors)))
        results.extend(normalize_dependency_changes(diff_dependencies(head_deps, base_deps)))

        for r in results:
            if isinstance(r.get("file"), str):
                r["file"] = _clean_path(r["file"])

        print(json.dumps(results))
        sys.exit(0)
    except (LintError, SecurityScanError, TypeCheckError, DependencyDiffError) as e:
        print(f"analysis error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"unexpected error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()