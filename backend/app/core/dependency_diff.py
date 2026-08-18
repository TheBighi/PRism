"""
dependency_diff.py — diff dependency manifests (requirements.txt / package.json)
between the base and head commits of a PR and report version changes introduced
by the diff.

Like the other analysis modules it normalizes findings into:

    {file, line, severity, category, source, message}

Parsing is purely in-memory (no lockfiles, node_modules or other temp files are
ever created).
"""

import json
import re
from collections import namedtuple
from pathlib import Path

DEPENDENCY_FILES = {"requirements.txt", "package.json"}

# (file, name, section, kind, old_version, new_version)
DependencyChange = namedtuple(
    "DependencyChange",
    ["file", "name", "section", "kind", "old_version", "new_version"],
)

_REQ_RE = re.compile(
    r"""
    ^([A-Za-z0-9._-]+)          # 1: package name
    (?:\[[^\]]*\])?              # optional extras, e.g. arcade[dev]
    \s*
    (==|>=|<=|~=|!=|>|<)?        # 2: operator (optional)
    \s*
    ([^\s;#]*)                   # 3: version (optional, may be empty)
    """,
    re.VERBOSE,
)

class DependencyDiffError(Exception):
    pass


def _parse_requirements(path: Path) -> dict[str, namedtuple]:
    """name==version pins, and unpinned/range specs -> {lowercased_name: Dependency}."""
    deps = {}
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return deps

    for line in lines:
        line = line.strip()
        if not line or line.startswith(("#", "-", "--")):
            continue

        m = _REQ_RE.match(line)
        if not m:
            continue
        name, op, version = m.groups()
        name = name.strip()
        if not name:
            continue

        if op == "==" and version:
            deps[name.lower()] = (name, version, "")
        elif op and version:
            deps[name.lower()] = (name, f"{op}{version}", "")
        else:
            deps[name.lower()] = (name, None, "")

    return deps


def _parse_package_json(path: Path) -> dict[str, namedtuple]:
    try:
        data = json.loads(path.read_text(errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise DependencyDiffError(f"could not parse {path.name}: {e}")

    deps = {}
    for section in ("dependencies", "devDependencies"):
        for name, version in (data.get(section) or {}).items():
            deps[name.lower()] = (name, version, section)
    return deps


def dependency_state(repo_dir: Path) -> dict[str, dict]:
    """Parse every dependency manifest in a checkout ->
    {repo_path: {name: (display_name, version, section)}}."""
    state = {}
    for path in repo_dir.glob("**/package.json"):
        parts = path.parts
        if "node_modules" in parts or ".git" in parts:
            continue
        state[path.relative_to(repo_dir).as_posix()] = _parse_package_json(path)
    for path in repo_dir.glob("**/requirements.txt"):
        parts = path.parts
        if "node_modules" in parts or ".git" in parts:
            continue
        state[path.relative_to(repo_dir).as_posix()] = _parse_requirements(path)
    return state


def diff_dependencies(head_state: dict, base_state: dict) -> list[DependencyChange]:
    changes = []
    files = set(head_state) | set(base_state)
    for filename in sorted(files):
        head_deps = head_state.get(filename, {})
        base_deps = base_state.get(filename, {})

        for name, (disp, version, section) in head_deps.items():
            base = base_deps.get(name)
            if base is None:
                changes.append(DependencyChange(filename, disp, section, "added", None, version))
            elif base[1] != version:
                changes.append(
                    DependencyChange(filename, disp, section, "changed", base[1], version)
                )

        for name, (disp, version, section) in base_deps.items():
            if name not in head_deps:
                changes.append(DependencyChange(filename, disp, section, "removed", version, None))

    return changes


def normalize_dependency_changes(changes: list[DependencyChange]) -> list[dict]:
    def fmt(name, version):
        return name if version is None else f"{name}@{version}"

    normalized = []
    for c in sorted(changes, key=lambda c: (c.file, c.name)):
        if c.kind == "added":
            message = f"+ {fmt(c.name, c.new_version)}"
        elif c.kind == "removed":
            message = f"- {fmt(c.name, c.old_version)}"
        else:
            old = c.old_version if c.old_version is not None else "unpinned"
            new = c.new_version if c.new_version is not None else "unpinned"
            message = f"{c.name}: {old} -> {new}"
        if c.section:
            message = f"{message} ({c.section})"
        normalized.append({
            "file": c.file,
            "line": 0,
            "severity": "warning",
            "category": "dependency",
            "source": "dependency-diff",
            "message": message,
        })
    return normalized


def diff_dependency_files(head_dir: Path, base_dir: Path) -> list[dict]:
    """Convenience wrapper mirroring lint_files/scan_files' signature shape."""
    return normalize_dependency_changes(
        diff_dependencies(dependency_state(head_dir), dependency_state(base_dir))
    )