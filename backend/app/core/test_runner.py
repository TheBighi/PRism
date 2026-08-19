"""
app/core/test_runner.py

Runs only the "affected" test files identified by test_mapping.py, captures
pass/fail per test file, and measures coverage of the *changed source files*
(not the whole repo — that would be slow and mostly noise for a PR check).

Assumes pytest + coverage.py are available for Python, and jest is available
(with its built-in --coverage) for JS/TS. These are installed in
Dockerfile.analysis (pytest & coverage via pip, jest global via npm).
"""
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

PY_SUFFIX = ".py"
JS_SUFFIXES = (".js", ".jsx", ".ts", ".tsx")


class TestRunError(Exception):
    pass


def _truncate(text: str, limit: int = 600) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + "..."


def _split_by_kind(files: list[str]) -> tuple[list[str], list[str]]:
    py = [f for f in files if f.endswith(PY_SUFFIX)]
    js = [f for f in files if f.endswith(JS_SUFFIXES)]
    return py, js


# ---------------------------------------------------------------------------
# Running tests (pass/fail)
# ---------------------------------------------------------------------------

def run_tests(repo_dir: Path, test_files: list[str]) -> list[dict]:
    """Run only the given test files.

    Returns one entry per test file:
        {"test_file": str, "status": "passed"|"failed"|"error", "source": "pytest"|"jest"}

    A test file that doesn't exist in repo_dir is skipped defensively (the
    caller — run_analysis.py — should already have filtered to existing
    files, but base-commit runs are a case where a candidate may have
    vanished).
    """
    existing = [f for f in test_files if (repo_dir / f).is_file()]
    py_files, js_files = _split_by_kind(existing)

    results = []
    if py_files:
        results.extend(_run_pytest(repo_dir, py_files))
    if js_files:
        results.extend(_run_jest(repo_dir, js_files))
    return results


def _run_pytest(repo_dir: Path, files: list[str]) -> list[dict]:
    junit_name = ".pr_analysis_junit.xml"
    # -o junit_family=legacy: the default junit_family omits the `file`
    # attribute on <testcase>, only giving a dotted classname. legacy
    # (xunit1) format includes file="tests/test_foo.py" directly, which is
    # what we need to map results back to requested test files reliably.
    cmd = [
        "python3", "-m", "pytest", "-q",
        "-o", "junit_family=legacy",
        "--continue-on-collection-errors",
        f"--junitxml={junit_name}",
        *files,
    ]
    proc = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True, timeout=600, check=False)
    # 0 = all passed, 1 = some failed, 5 = no tests collected. All are "ran ok".
    if proc.returncode not in (0, 1, 5):
        raise TestRunError(f"pytest failed to run: {proc.stderr.strip() or proc.stdout.strip()}")

    junit_path = repo_dir / junit_name
    if not junit_path.is_file():
        return [{"test_file": f, "status": "error", "source": "pytest"} for f in files]

    try:
        results = _parse_junit(junit_path, files)
    finally:
        junit_path.unlink(missing_ok=True)
    return results


def _parse_junit(junit_path: Path, requested_files: list[str]) -> list[dict]:
    root = ET.parse(junit_path).getroot()

    status_by_file: dict[str, str] = {}
    message_by_file: dict[str, str] = {}
    for testcase in root.iter("testcase"):
        file_attr = testcase.get("file")
        if not file_attr:
            continue
        file_attr = Path(file_attr).as_posix()

        status = "passed"
        failure = testcase.find("failure")
        error = testcase.find("error")
        if failure is not None:
            status = "failed"
        elif error is not None:
            status = "error"

        current = status_by_file.get(file_attr)
        if current is None or (current == "passed" and status != "passed"):
            status_by_file[file_attr] = status
            detail = (failure if failure is not None else error)
            if detail is not None and (detail.text or "").strip():
                message_by_file[file_attr] = _truncate(detail.text)

    return [
        {
            "test_file": f,
            # Not present in the junit report at all -> pytest couldn't
            # collect it (import error, syntax error, etc).
            "status": status_by_file.get(f, "error"),
            "source": "pytest",
            "message": message_by_file.get(f),
        }
        for f in requested_files
    ]


def _run_jest(repo_dir: Path, files: list[str]) -> list[dict]:
    out_name = ".pr_analysis_jest.json"
    cmd = ["npx", "--yes", "jest", "--json", f"--outputFile={out_name}", *files]
    proc = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True, timeout=600, check=False)
    if proc.returncode not in (0, 1):
        raise TestRunError(f"jest failed to run: {proc.stderr.strip() or proc.stdout.strip()}")

    out_path = repo_dir / out_name
    if not out_path.is_file():
        return [{"test_file": f, "status": "error", "source": "jest"} for f in files]

    try:
        data = json.loads(out_path.read_text())
    except json.JSONDecodeError as e:
        raise TestRunError(f"could not parse jest output: {e}")
    finally:
        out_path.unlink(missing_ok=True)

    status_by_file = {}
    message_by_file = {}
    for tr in data.get("testResults", []):
        try:
            rel = Path(tr["name"]).resolve().relative_to(repo_dir.resolve()).as_posix()
        except ValueError:
            continue
        status_by_file[rel] = "passed" if tr.get("status") == "passed" else "failed"

        messages = []
        for ar in tr.get("assertionResults", []):
            if ar.get("status") != "passed":
                messages.extend(ar.get("failureMessages", []))
        if messages:
            message_by_file[rel] = _truncate("\n".join(messages))

    return [
        {
            "test_file": f,
            "status": status_by_file.get(f, "error"),
            "source": "jest",
            "message": message_by_file.get(f),
        }
        for f in files
    ]


# ---------------------------------------------------------------------------
# Coverage of the changed source files
# ---------------------------------------------------------------------------

def get_coverage(repo_dir: Path, test_files: list[str], source_files: list[str]) -> dict[str, float | None]:
    """Line-coverage % (0-100) of each source file, exercised only by
    test_files. None means "not measurable" (e.g. a JS source file but no
    JS tests were run, or the coverage tool wasn't available)."""
    # Same existence filter as run_tests: on the base checkout a candidate
    # test added by the PR won't exist, and pytest hard-fails (exit 4) on
    # nonexistent paths — that would abort the whole analysis.
    existing_tests = [f for f in test_files if (repo_dir / f).is_file()]
    py_tests, js_tests = _split_by_kind(existing_tests)
    py_sources = [f for f in source_files if f.endswith(PY_SUFFIX)]
    js_sources = [f for f in source_files if f.endswith(JS_SUFFIXES)]

    coverage: dict[str, float | None] = {f: None for f in source_files}
    if py_tests and py_sources:
        coverage.update(_py_coverage(repo_dir, py_tests, py_sources))
    if js_tests and js_sources:
        coverage.update(_js_coverage(repo_dir, js_tests, js_sources))
    return coverage


def _py_coverage(repo_dir: Path, test_files: list[str], source_files: list[str]) -> dict[str, float | None]:
    include = ",".join(source_files)
    run_cmd = ["python3", "-m", "coverage", "run", f"--include={include}", "-m", "pytest", "-q", *test_files]
    proc = subprocess.run(run_cmd, cwd=repo_dir, capture_output=True, text=True, timeout=600, check=False)
    if proc.returncode not in (0, 1, 5):
        raise TestRunError(f"coverage run failed: {proc.stderr.strip() or proc.stdout.strip()}")

    json_cmd = ["python3", "-m", "coverage", "json", "-o", "-"]
    json_proc = subprocess.run(json_cmd, cwd=repo_dir, capture_output=True, text=True, timeout=60, check=False)
    if json_proc.returncode != 0:
        # e.g. "No data to report" when nothing ran / nothing matched --include
        return {f: None for f in source_files}

    try:
        data = json.loads(json_proc.stdout)
    except json.JSONDecodeError as e:
        raise TestRunError(f"could not parse coverage json: {e}")

    files_data = data.get("files", {})
    return {
        f: files_data[f]["summary"]["percent_covered"] if f in files_data else None
        for f in source_files
    }


def _js_coverage(repo_dir: Path, test_files: list[str], source_files: list[str]) -> dict[str, float | None]:
    cmd = ["npx", "--yes", "jest", "--coverage", "--coverageReporters=json-summary", *test_files]
    proc = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True, timeout=600, check=False)
    if proc.returncode not in (0, 1):
        raise TestRunError(f"jest coverage failed: {proc.stderr.strip() or proc.stdout.strip()}")

    summary_path = repo_dir / "coverage" / "coverage-summary.json"
    if not summary_path.is_file():
        return {f: None for f in source_files}

    try:
        data = json.loads(summary_path.read_text())
    except json.JSONDecodeError as e:
        raise TestRunError(f"could not parse jest coverage summary: {e}")

    result = {}
    for f in source_files:
        abs_key = str((repo_dir / f).resolve())
        entry = data.get(abs_key)
        result[f] = entry["lines"]["pct"] if entry else None
    return result


# ---------------------------------------------------------------------------
# Combining head vs. base into a delta
# ---------------------------------------------------------------------------

def coverage_delta(head_coverage: dict[str, float | None], base_coverage: dict[str, float | None]) -> dict:
    """Per-file coverage change, head vs. base."""
    delta = {}
    for f, head_pct in head_coverage.items():
        base_pct = base_coverage.get(f)
        if head_pct is None:
            delta[f] = {"head": None, "base": base_pct, "delta": None, "note": "not measurable"}
        elif base_pct is None:
            delta[f] = {"head": head_pct, "base": None, "delta": None, "note": "no baseline (new file or no base tests)"}
        else:
            delta[f] = {"head": head_pct, "base": base_pct, "delta": round(head_pct - base_pct, 2)}
    return delta


# ---------------------------------------------------------------------------
# Checklist: affected vs. skipped
# ---------------------------------------------------------------------------

_TEST_GLOBS = (
    "test_*.py", "*_test.py",
    "*.test.js", "*.test.jsx", "*.test.ts", "*.test.tsx",
    "*.spec.js", "*.spec.jsx", "*.spec.ts", "*.spec.tsx",
    "__tests__/*.js", "__tests__/*.jsx", "__tests__/*.ts", "__tests__/*.tsx",
)


def _discover_all_test_files(repo_dir: Path) -> set[str]:
    found = set()
    for pattern in _TEST_GLOBS:
        for p in repo_dir.rglob(pattern):
            if "node_modules" in p.parts or ".git" in p.parts:
                continue
            found.add(p.relative_to(repo_dir).as_posix())
    return found


def build_test_checklist(repo_dir: Path, candidate_tests: list[str], test_results: list[dict]) -> dict:
    """Formats affected vs. skipped tests for the PR analysis output."""
    all_test_files = _discover_all_test_files(repo_dir)
    affected_set = set(candidate_tests)

    affected = [{"test_file": r["test_file"], "status": r["status"]} for r in test_results]
    skipped = sorted(all_test_files - affected_set)

    return {"affected": affected, "skipped": skipped}