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
  - test_results: test execution outcomes
"""

WEIGHTS = {
    "sensitive_file": 15,
    "diff_size": 10,
    "dependency_change": 5,
    "static_analysis": 30,
    "coverage_decrease": 10,
    "historical_risk": 10,
    "test_failure": 20,
}
assert sum(WEIGHTS.values()) == 100

# Substring match against changed file paths (lowercased).
SENSITIVE_PATTERNS = (
    "auth", "login", "session", "token", "password", "secret", "credential",
    "payment", "billing", "stripe", "charge", "invoice",
    "db", "database", "migrat", "schema",
    "permission", "role", "acl", "security",
    "main", "app", "config", "setup", "docker", "nginx",
    "env", "key", "cert", "ssl", "tls", "crypto",
    "user", "admin", "root", "server", "deploy",
)

# Severity weights — security-critical findings hit much harder.
# A single shell=True or hardcoded password should tank the score.
SEVERITY_WEIGHT = {
    "critical": 12,
    "high": 6,
    "error": 3,
    "warning": 1,
    "info": 0.5,
}

# Security findings get an extra multiplier on top of severity weight.
SECURITY_MULTIPLIER = 1.5

# Caps that map a raw count onto a 0.0-1.0 scale.
DIFF_SIZE_CAP = 500
STATIC_FINDINGS_CAP = 15    # lowered from 30 — security findings should dominate
COVERAGE_DECREASE_CAP = 20
TEST_FAILURE_PENALTY = 0.5  # each failing test adds this to the score (capped at 1.0)


# --- Sub-scores ------------------------------------------------------------

def _sensitive_file_score(filenames: list[str]) -> dict:
    matched = [f for f in filenames if any(p in f.lower() for p in SENSITIVE_PATTERNS)]
    if not matched:
        return {"score": 0.0, "matched_files": []}
    score = min((len(matched) / len(filenames)) * 2, 1.0)
    return {"score": score, "matched_files": matched}


def _diff_size_score(diff_stats: list[dict]) -> dict:
    total_changes = sum(d.get("changes", 0) for d in diff_stats)
    score = min(total_changes / DIFF_SIZE_CAP, 1.0)
    return {"score": score, "total_changes": total_changes, "files_changed": len(diff_stats)}


def _dependency_score(grouped_results: list[dict]) -> dict:
    dep_section = next((g for g in grouped_results if g.get("type") == "dependencies"), None)
    findings = dep_section["results"] if dep_section else []
    added_or_changed = [f for f in findings if not f["message"].startswith("-")]
    score = 1.0 if added_or_changed else 0.0
    return {"score": score, "changes": [f["message"] for f in findings]}


def _static_analysis_score(grouped_results: list[dict]) -> dict:
    weighted_total = 0.0
    counts = {"critical": 0, "high": 0, "error": 0, "warning": 0, "info": 0}
    security_count = 0

    for group in grouped_results:
        gtype = group.get("type")
        if gtype not in ("security", "linting", "types"):
            continue
        is_security = gtype == "security"

        for finding in group["results"]:
            sev = finding.get("severity", "warning")
            w = SEVERITY_WEIGHT.get(sev, 1)
            if is_security:
                w *= SECURITY_MULTIPLIER
                security_count += 1
            weighted_total += w
            counts[sev] = counts.get(sev, 0) + 1

    score = min(weighted_total / STATIC_FINDINGS_CAP, 1.0)
    return {
        "score": score,
        "weighted_total": round(weighted_total, 1),
        "counts": counts,
        "security_findings": security_count,
    }


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


def _test_failure_score(grouped_results: list[dict]) -> dict:
    test_section = next((g for g in grouped_results if g.get("type") == "test_results"), None)
    findings = test_section.get("results", []) if test_section else []

    failed = [f for f in findings if f.get("severity") == "error"]
    passed = [f for f in findings if f.get("severity") != "error"]

    if not findings:
        return {"score": 0.0, "failed": 0, "passed": 0, "total": 0}

    fail_ratio = len(failed) / len(findings)
    score = min(fail_ratio * 2, 1.0)  # any failure is bad, all failures = 1.0

    return {
        "score": score,
        "failed": len(failed),
        "passed": len(passed),
        "total": len(findings),
        "failed_tests": [f.get("filename", f.get("message", "")) for f in failed],
    }


# --- Entry point -------------------------------------------------------

def compute_risk_score(analysis_output: list[dict], filenames: list[str]) -> dict:
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
        "test_failure": _test_failure_score(analysis_output),
    }

    breakdown = {}
    total = 0.0
    for category, weight in WEIGHTS.items():
        sub = subscores[category]
        contribution = sub["score"] * weight
        total += contribution
        breakdown[category] = {"weight": weight, "contribution": round(contribution, 2), **sub}

    return {"total": round(total, 1), "breakdown": breakdown}
