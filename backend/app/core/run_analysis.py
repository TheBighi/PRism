import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from dependency_diff import (
    DependencyDiffError,
    dependency_state,
    diff_dependencies,
    normalize_dependency_changes,
)
from linting import LintError, clone_repo_at_sha, lint_files
from security_scan import SecurityScanError, scan_files
from test_mapping import map_source_to_tests
from test_runner import (
    TestRunError,
    build_test_checklist,
    coverage_delta,
    get_coverage,
    run_tests,
)
from type_check import TypeCheckError, new_errors, type_check_files


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


def _normalize_test_failures(test_results: list[dict]) -> list[dict]:
    """Fold failed/errored test runs into the same finding shape as every
    other tool (lint/security/type/dependency). Passing tests aren't
    findings — they're only reflected in test_checklist."""
    normalized = []
    for r in test_results:
        if r["status"] == "passed":
            continue
        normalized.append({
            "file": r["test_file"],
            "line": 0,  # junit/jest give us file-level results, not a line
            "severity": "error",
            "category": "test-failure" if r["status"] == "failed" else "test-collection-error",
            "source": r["source"],
            "message": r.get("message") or f"test file {r['status']}",
        })
    return normalized


def _clean_path(f: str) -> str:
    """Normalize a tool-reported path to a repo-relative posix path."""
    return Path(f).as_posix().removeprefix("./")


# Orders the grouped sections in output, and maps each tool's `source`
# to its top-level type. Anything unmapped falls into "other".
_SOURCE_TYPE = {
    "ruff": "linting",
    "eslint": "linting",
    "bandit": "security",
    "npm-audit": "security",
    "mypy": "types",
    "tsc": "types",
    "dependency-diff": "dependencies",
    "pytest": "tests",
    "jest": "tests",
}
_TYPE_ORDER = ["security", "linting", "types", "dependencies", "tests", "other"]


def _group_by_type(results: list[dict]) -> list[dict]:
    """Group normalized findings under their top-level type:
        {"type": "security", "results": [{finding}, ...]}
    Types that produced no findings are omitted."""
    grouped: dict[str, list[dict]] = {}
    for r in results:
        t = _SOURCE_TYPE.get(r.get("source"), "other")
        grouped.setdefault(t, []).append(r)

    return [
        {"type": t, "results": grouped[t]}
        for t in _TYPE_ORDER
        if t in grouped
    ]


def main():
    if len(sys.argv) < 4:
        print("usage: run_analysis.py <clone_url> <base_sha> <head_sha> [files...]", file=sys.stderr)
        sys.exit(2)

    clone_url, base_sha, head_sha, *filenames = sys.argv[1:]

    tmp_dir = Path(tempfile.mkdtemp(prefix="pr-analysis-"))
    try:
        clone_repo_at_sha(clone_url, head_sha, tmp_dir)

        candidate_tests = map_source_to_tests(filenames, tmp_dir)

        results = []
        results.extend(lint_files(tmp_dir, filenames))
        results.extend(scan_files(tmp_dir, filenames))

        head_type_errors = type_check_files(tmp_dir, filenames)
        head_deps = dependency_state(tmp_dir)
        head_test_results = run_tests(tmp_dir, candidate_tests)
        head_coverage = get_coverage(tmp_dir, candidate_tests, filenames)

        _checkout(tmp_dir, clone_url, base_sha)
        base_type_errors = type_check_files(tmp_dir, filenames)
        base_deps = dependency_state(tmp_dir)
        base_coverage = get_coverage(tmp_dir, candidate_tests, filenames)
        _checkout(tmp_dir, clone_url, head_sha)  # restore for anything downstream

        results.extend(_normalize_type_errors(new_errors(head_type_errors, base_type_errors)))
        results.extend(normalize_dependency_changes(diff_dependencies(head_deps, base_deps)))
        results.extend(_normalize_test_failures(head_test_results))

        for r in results:
            if isinstance(r.get("file"), str):
                r["file"] = _clean_path(r["file"])

        output = [*_group_by_type(results)]

        output.append({
            "type": "test_mapping",
            "candidate_tests": candidate_tests,
        })
        output.append({
            "type": "test_checklist",
            **build_test_checklist(tmp_dir, candidate_tests, head_test_results),
        })
        output.append({
            "type": "coverage_delta",
            "coverage": coverage_delta(head_coverage, base_coverage),
        })

        print(json.dumps(output))
        sys.exit(0)
    except (LintError, SecurityScanError, TypeCheckError, DependencyDiffError, TestRunError) as e:
        print(f"analysis error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"unexpected error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()