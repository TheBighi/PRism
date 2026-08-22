import json
from typing import Any

from app.schemas.explanation import PRExplanation


def build_explanation_prompt(results: list[dict[str, Any]]) -> str:
    findings = []
    dependencies = []
    test_mapping = None
    test_checklist = None
    coverage = None
    diff_stats = None
    risk_score = None

    for result in results:
        result_type = result.get("type")

        if result_type in {"security", "linting", "types"}:
            for finding in result.get("results", []):
                findings.append({
                    "type": result_type,
                    "file": finding.get("file"),
                    "line": finding.get("line"),
                    "column": finding.get("column"),
                    "severity": finding.get("severity"),
                    "category": finding.get("category"),
                    "source": finding.get("source"),
                    "message": finding.get("message"),
                })

        elif result_type == "dependencies":
            dependencies.extend(result.get("results", []))

        elif result_type == "test_mapping":
            test_mapping = result

        elif result_type == "test_checklist":
            test_checklist = result

        elif result_type == "coverage_delta":
            coverage = result.get("coverage")

        elif result_type == "diff_stats":
            diff_stats = result.get("stats")

        elif result_type == "risk_score":
            risk_score = result

    evidence = {
        "findings": findings,
        "dependencies": dependencies,
        "test_mapping": test_mapping,
        "test_checklist": test_checklist,
        "coverage": coverage,
        "diff_stats": diff_stats,
        "risk_score": risk_score,
    }

    return f"""
You are a senior software engineer reviewing a pull request.

Analyze the provided evidence and produce a concise engineering assessment.

Rules:
- Use ONLY the provided evidence.
- Do not invent facts.
- Do not invent vulnerabilities or behavior not supported by the evidence.
- Prioritize security, correctness, reliability, testing, and merge readiness.
- Group findings that represent the same underlying problem.
- Do not simply repeat every analyzer finding.
- Treat the deterministic risk score as supporting evidence, not as the final judgment.
- Failing tests are highly relevant to merge readiness.
- Minor lint/style issues should not dominate the explanation.

Return a JSON object matching the required output schema exactly.

PR ANALYSIS EVIDENCE:

{json.dumps(evidence, indent=2, ensure_ascii=False, default=str)}
""".strip()


async def call_llm(prompt: str) -> PRExplanation:
    return None