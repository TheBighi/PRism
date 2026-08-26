import json
import logging
from typing import Any

from google import genai
from google.genai import types

from pydantic import BaseModel, ValidationError

from app.config.config import get_settings

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
- Do not invent vulnerabilities or behavior that is not supported by the evidence.
- Prioritize issues that affect security, correctness, reliability, testing, or merge safety.
- Group findings that represent the same underlying problem.
- Do not simply repeat every analyzer finding.
- Treat the deterministic risk score as supporting evidence, not as the final judgment.
- A failing test is highly relevant to merge readiness.
- Security findings should be prioritized when they represent meaningful risk.
- Minor style or lint findings should not dominate the explanation.
- Use the provided evidence when explaining each risk.
- Keep the response concise and technically precise.

Return a JSON object matching the required output schema.

The output must contain:

summary:
A concise 2-4 sentence summary of the PR's most important issues.

overall_risk:
One of:
- critical
- high
- medium
- low

top_risks:
The 1-5 most important issues.
Each risk must contain:
- title
- severity
- category
- explanation
- evidence
- files
- lines

recommendation:
Must contain:
- priority: block, changes_requested, review, or approve
- summary
- actions

The recommendation should reflect the actual evidence.
Do not recommend blocking a PR solely because of minor lint warnings.

PR ANALYSIS EVIDENCE:

{json.dumps(
    evidence,
    indent=2,
    ensure_ascii=False,
    default=str
)}
""".strip()


logger = logging.getLogger(__name__)
settings = get_settings()

client = genai.Client(api_key=settings.gemini_api_key)


def _strict_schema(schema: Any) -> Any:
    """Convert a pydantic JSON schema into an OpenAI strict-mode compatible schema."""
    if isinstance(schema, list):
        return [_strict_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema

    result = {
        key: _strict_schema(value)
        for key, value in schema.items()
        if key != "default"
    }

    if "properties" in result:
        result["required"] = list(result["properties"])
        result["additionalProperties"] = False
    return result


async def call_llm[T: BaseModel](
    prompt: str,
    response_model: type[T],
    *,
    max_retries: int = 2,
) -> T:
    """Call Gemini and parse the response into response_model."""
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            response = await client.aio.models.generate_content(
                model=settings.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=response_model,
                    temperature=0,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                ),
            )
            # response.parsed is already validated by the SDK when it succeeds
            if response.parsed is not None:
                return response.parsed
            # fallback: validate the raw text ourselves
            return response_model.model_validate_json(response.text)

        except (ValidationError, ValueError) as e:
            last_error = e
            logger.warning(
                "call_llm attempt %d/%d failed: %s",
                attempt + 1, max_retries + 1, e,
            )

    raise RuntimeError(
        f"LLM call failed to produce valid {response_model.__name__} "
        f"after {max_retries + 1} attempts"
    ) from last_error