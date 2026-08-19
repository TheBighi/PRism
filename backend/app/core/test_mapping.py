"""
app/core/test_mapping.py

Maps changed source files to candidate test files using plain naming
conventions (no import-graph analysis). For each changed file we generate
a handful of plausible test paths and keep only the ones that actually
exist in the checked-out repo.
"""

from pathlib import Path

# Only these are treated as "source" — anything else (configs, locks,
# docs, etc.) is skipped outright.
SOURCE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx"}

# Exact basenames that are never worth mapping to tests.
SKIP_BASENAMES = {
    "__init__.py",
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Pipfile.lock",
    "setup.py",
    "setup.cfg",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "tsconfig.json",
    "tsconfig.base.json",
}


def _is_already_a_test(path: Path) -> bool:
    """Don't try to map a test file to... itself."""
    name = path.name
    stem = path.stem
    return (
        name.startswith("test_")
        or stem.endswith(("_test", ".test", ".spec"))
    )


def _is_source_file(rel_path: str) -> bool:
    path = Path(rel_path)
    if path.suffix not in SOURCE_EXTENSIONS:
        return False
    if path.name in SKIP_BASENAMES:
        return False
    return not _is_already_a_test(path)


def _candidates_for(rel_path: str) -> list[str]:
    """Naming-convention candidates for one changed file, e.g. src/foo.py:
      - tests/test_foo.py                 (flat)
      - tests/src/foo_test.py             (mirrored)
      - tests/src/test_foo.py             (mirrored)
      - src/test_foo.py                   (co-located)
    For JS/TS, jest's conventions replace the pytest ones:
      - src/foo.test.js / src/foo.spec.js (co-located)
      - __tests__/foo.test.js             (jest __tests__ dir)
    """
    path = Path(rel_path)
    stem = path.stem
    suffix = path.suffix
    parent = path.parent  # "." for top-level files

    candidates = [
        Path("tests") / f"test_{stem}{suffix}",
    ]

    if parent == Path("."):
        mirrored_dir = Path("tests")
    else:
        mirrored_dir = Path("tests") / parent
    candidates.append(mirrored_dir / f"{stem}_test{suffix}")
    candidates.append(mirrored_dir / f"test_{stem}{suffix}")

    candidates.append(parent / f"test_{stem}{suffix}")

    if suffix in (".js", ".jsx", ".ts", ".tsx"):
        candidates.append(parent / f"{stem}.test{suffix}")
        candidates.append(parent / f"{stem}.spec{suffix}")
        candidates.append(Path("__tests__") / f"{stem}.test{suffix}")
        candidates.append(Path("__tests__") / f"{stem}.spec{suffix}")

    return [c.as_posix() for c in candidates]


def map_source_to_tests(changed_files: list[str], repo_dir: Path) -> list[str]:
    """Given the list of changed files and the checked-out repo dir, return
    the candidate test files that actually exist on disk.

    Result is deduped and sorted for stable output.
    """
    found: set[str] = set()

    for rel_path in changed_files:
        if not _is_source_file(rel_path):
            continue

        for candidate in _candidates_for(rel_path):
            if (repo_dir / candidate).is_file():
                found.add(candidate)

    return sorted(found)