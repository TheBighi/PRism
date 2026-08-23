from typing import Literal

from pydantic import BaseModel, Field


class RiskItem(BaseModel):
    title: str
    severity: Literal["critical", "high", "medium", "low"]
    category: str
    explanation: str
    evidence: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    lines: list[int] = Field(default_factory=list)


class Recommendation(BaseModel):
    priority: Literal["block", "changes_requested", "review", "approve"]
    summary: str
    actions: list[str] = Field(default_factory=list)


class PRExplanation(BaseModel):
    summary: str
    overall_risk: Literal["critical", "high", "medium", "low"]
    top_risks: list[RiskItem] = Field(default_factory=list)
    recommendation: Recommendation