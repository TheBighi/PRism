"""
app/core/risk_score.py

Computes a weighted risk score (0-100) for a PR from the normalized analysis
output that run_analysis.py already produces. No new tools run here — this
is pure aggregation/scoring over existing findings.

Inputs consumed (all already exist in the pipeline):
  - diff_stats: per-file additions/deletions/status
  - grouped findings: security / linting / types (severity-tagged)
  - dependencies: added/changed/removed entries
  - coverage_delta: per-file head/base/delta coverage
"""

WEIGHTS = {
    "sensitive_file": 20,
    "diff_size": 15,
    "dependency_change": 10,
    "static_analysis": 25,
    "coverage_decrease": 15,
    "historical_risk": 15,
}
assert sum(WEIGHTS.values()) == 100

# Substring match against changed file paths (lowercased). Deliberately
# broad/cheap rather than a real ownership map — tighten as needed.
SENSITIVE_PATTERNS = (
    "auth", "login", "session", "token", "password", "secret", "credential",
    "payment", "billing", "stripe", "charge", "invoice",
    "db", "database", "migrat", "schema",
    "permission", "role", "acl", "security",
)

SEVERITY_WEIGHT = {"error": 3, "warning": 1}

# Caps that map a raw count onto a 0.0-1.0 scale. These are guesses to get
# you started; once you have a few weeks of real PR data, replace them with
# actual percentiles (e.g. cap diff size at your p90 changed-lines count).
DIFF_SIZE_CAP = 500          # total lines changed -> 1.0
STATIC_FINDINGS_CAP = 30     # severity-weighted finding total -> 1.0
COVERAGE_DECREASE_CAP = 20   # percentage-point coverage drop -> 1.0


# --- Sub-scores ------------------------------------------------------------
# Each returns {"score": 0.0-1.0, ...evidence used to compute it} so the
# breakdown is auditable, not just a number.

def _sensitive_file_score(filenames: list[str]) -> dict:
    matched = [f for f in filenames if any(p in f.lower() for p in SENSITIVE_PATTERNS)]
    if not matched:
        return {"score": 0.0, "matched_files": []}
    # x2 so touching 1 of e.g. 4 files still registers meaningfully, rather
    # than requiring half the PR to be "sensitive" before it moves the score.
    score = min((len(matched) / len(filenames)) * 2, 1.0)
    return {"score": score, "matched_files": matched}


def _diff_size_score(diff_stats: list[dict]) -> dict:
    total_changes = sum(d.get("changes", 0) for d in diff_stats)
    score = min(total_changes / DIFF_SIZE_CAP, 1.0)
    return {"score": score, "total_changes": total_changes, "files_changed": len(diff_stats)}


def _dependency_score(grouped_results: list[dict]) -> dict:
    dep_section = next((g for g in grouped_results if g.get("type") == "dependencies"), None)
    findings = dep_section["results"] if dep_section else []
    # "-" prefix (see dependency_diff.normalize_dependency_changes) means a
    # removal, which isn't what this sub-score is meant to flag.
    added_or_changed = [f for f in findings if not f["message"].startswith("-")]
    score = 1.0 if added_or_changed else 0.0
    return {"score": score, "changes": [f["message"] for f in findings]}


def _static_analysis_score(grouped_results: list[dict]) -> dict:
    weighted_total = 0
    counts = {"error": 0, "warning": 0}
    for group in grouped_results:
        if group.get("type") not in ("security", "linting", "types"):
            continue
        for finding in group["results"]:
            sev = finding.get("severity", "warning")
            weighted_total += SEVERITY_WEIGHT.get(sev, 1)
            counts[sev] = counts.get(sev, 0) + 1
    score = min(weighted_total / STATIC_FINDINGS_CAP, 1.0)
    return {"score": score, "weighted_total": weighted_total, "counts": counts}


def _coverage_decrease_score(coverage: dict) -> dict:
    worst = 0.0
    worst_file = None
    for filename, entry in coverage.items():
        delta = entry.get("delta")
        if delta is not None and delta < 0 and -delta > worst:
            worst, worst_file = -delta, filename
    score = min(worst / COVERAGE_DECREASE_CAP, 1.0)
    return {"score": score, "worst_decrease": round(worst, 2), "file": worst_file}


def _historical_risk_score(grouped_results: list[dict]) -> dict:
    historical = next((g for g in grouped_results if g.get("type") == "historical_risk"), None)
    files = historical.get("files", {}) if historical else {}
    if not files:
        return {"score": 0.0, "files": {}, "note": "no history data yet"}

    worst = 0.0
    worst_file = None
    for filename, entry in files.items():
        s = entry.get("risk_score", 0) / 100.0
        if s > worst:
            worst, worst_file = s, filename

    return {"score": worst, "worst_file": worst_file, "files": files}


# --- Entry point -------------------------------------------------------

def compute_risk_score(analysis_output: list[dict], filenames: list[str]) -> dict:
    """
    analysis_output: the list run_analysis.py builds/prints (grouped findings
        plus the test_mapping / test_checklist / coverage_delta / diff_stats
        entries).
    filenames: the PR's changed files (same list passed into run_analysis.py).

    Returns:
        {
          "total": 0-100,
          "breakdown": {
            category: {"weight": int, "contribution": float, "score": float, ...evidence}
          }
        }
    """
    by_type = {g["type"]: g for g in analysis_output if "type" in g}
    diff_stats = by_type.get("diff_stats", {}).get("stats", [])
    coverage = by_type.get("coverage_delta", {}).get("coverage", {})

    subscores = {
        "sensitive_file": _sensitive_file_score(filenames),
        "diff_size": _diff_size_score(diff_stats),
        "dependency_change": _dependency_score(analysis_output),
        "static_analysis": _static_analysis_score(analysis_output),
        "coverage_decrease": _coverage_decrease_score(coverage),
        "historical_risk": _historical_risk_score(analysis_output),
    }

    breakdown = {}
    total = 0.0
    for category, weight in WEIGHTS.items():
        sub = subscores[category]
        contribution = sub["score"] * weight
        total += contribution
        breakdown[category] = {"weight": weight, "contribution": round(contribution, 2), **sub}

    return {"total": round(total, 1), "breakdown": breakdown}