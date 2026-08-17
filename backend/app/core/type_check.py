"""
type_check.py — run mypy/tsc against changed files and return only errors
introduced by the diff (i.e. absent on the base commit).
"""
import re
import subprocess
from collections import Counter, namedtuple
from pathlib import Path

TypeError_ = namedtuple("TypeError_", ["file", "line", "column", "code", "message", "tool"])

class TypeCheckError(Exception):
    pass

_MYPY_RE = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+):(?:(?P<col>\d+):)?\s*error:\s*"
    r"(?P<msg>.+?)(?:\s+\[(?P<code>[\w-]+)\])?$"
)
_TSC_RE = re.compile(
    r"^(?P<file>[^(]+)\((?P<line>\d+),(?P<col>\d+)\):\s*error\s+"
    r"(?P<code>TS\d+):\s*(?P<msg>.+)$"
)


def type_check_files(repo_dir: Path, filenames: list[str]) -> list[TypeError_]:
    """Run whichever type checker applies, based on file extensions present."""
    results: list[TypeError_] = []
    py_files = [f for f in filenames if f.endswith(".py")]
    ts_files = [f for f in filenames if f.endswith((".ts", ".tsx"))]
    js_files = [f for f in filenames if f.endswith((".js", ".jsx"))]

    if py_files:
        results.extend(_run_mypy(repo_dir, py_files))
    if ts_files or js_files:
        # if opted into JS checking
        if js_files and not _checks_js(repo_dir):
            js_files = []
        results.extend(_run_tsc(repo_dir, ts_files + js_files))
    return results


def _run_mypy(repo_dir: Path, files: list[str]) -> list[TypeError_]:
    cmd = ["mypy", "--show-error-codes", "--no-error-summary", "--no-color-output", *files]
    proc = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True, timeout=300)
    if proc.returncode not in (0, 1):  # 0 = clean, 1 = type errors found; anything else = tool failure
        raise TypeCheckError(f"mypy failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return _parse(proc.stdout, _MYPY_RE, "mypy")


def _run_tsc(repo_dir: Path, files: list[str]) -> list[TypeError_]:
    cmd = ["npx", "tsc", "--noEmit", "--pretty", "false", *files]
    proc = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True, timeout=300)
    if proc.returncode not in (0, 1, 2):
        raise TypeCheckError(f"tsc failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return _parse(proc.stdout, _TSC_RE, "tsc")

def _checks_js(repo_dir: Path) -> bool:
    tsconfig = repo_dir / "tsconfig.json"
    if not tsconfig.exists():
        return False
    try:
        import json as _json
        cfg = _json.loads(tsconfig.read_text())
        return bool(cfg.get("compilerOptions", {}).get("checkJs"))
    except Exception:
        return False

def _parse(output: str, pattern: re.Pattern, tool: str) -> list[TypeError_]:
    errors = []
    for line in output.splitlines():
        m = pattern.match(line.strip())
        if not m:
            continue
        errors.append(TypeError_(
            file=m.group("file"),
            line=int(m.group("line")),
            column=int(m.group("col") or 0),
            code=m.group("code") or "",
            message=m.group("msg").strip(),
            tool=tool,
        ))
    return errors


def new_errors(head_errors: list[TypeError_], base_errors: list[TypeError_]) -> list[TypeError_]:
    def sig(e: TypeError_):
        return (e.file, e.code, e.message)

    base_counts = Counter(sig(e) for e in base_errors)
    out = []
    for e in head_errors:
        s = sig(e)
        if base_counts[s] > 0:
            base_counts[s] -= 1
        else:
            out.append(e)
    return out