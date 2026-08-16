"""
run_analysis.py — entrypoint for the analysis container.
Usage: python run_analysis.py <clone_url> <head_sha> <filename1> [filename2 ...]
Prints normalized results as a single JSON array to stdout. All logging/errors go to stderr.
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

from linting import clone_repo_at_sha, lint_files, LintError
from security_scan import scan_files, SecurityScanError


def main():
    if len(sys.argv) < 3:
        print("usage: run_analysis.py <clone_url> <head_sha> [files...]", file=sys.stderr)
        sys.exit(2)

    clone_url, head_sha, *filenames = sys.argv[1:]

    tmp_dir = Path(tempfile.mkdtemp(prefix="pr-analysis-"))
    try:
        clone_repo_at_sha(clone_url, head_sha, tmp_dir)

        results = []
        results.extend(lint_files(tmp_dir, filenames))
        results.extend(scan_files(tmp_dir, filenames))

        print(json.dumps(results))
        sys.exit(0)
    except (LintError, SecurityScanError) as e:
        print(f"analysis error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"unexpected error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()