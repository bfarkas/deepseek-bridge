from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Versioned(StrictModel):
    schema_version: Literal["1.0"] = "1.0"


class Context(StrictModel):
    repository: str | None = None
    files: list[str] = Field(default_factory=list, max_length=20)
    text: str = ""
    diff: str = ""


class Ask(Versioned):
    task: str = Field(min_length=1, max_length=50000)
    context: Context = Field(default_factory=Context)
    mode: Literal["brainstorm", "review", "handoff"] = "brainstorm"
    model: Literal["consultant", "review", "research"] = "consultant"
    effort: Literal["low", "medium", "high", "max"] | None = None
    max_output_tokens: int = Field(default=4000, ge=1, le=8000)
    consultation_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class Finding(StrictModel):
    severity: Literal["info", "low", "medium", "high", "critical"]
    location: str
    rationale: str
    recommendation: str
    evidence: Literal["verified", "model_inference", "unverified_reference"] = "model_inference"


class ReviewReport(StrictModel):
    summary: str
    findings: list[Finding]
    risks: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)


class ResearchReport(StrictModel):
    summary: str
    findings: list[Finding]
    hypotheses: list[str]
    next_steps: list[str]
    risks: list[str]
    unresolved_questions: list[str]


class Usage(StrictModel):
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    provider_request_id: str | None = None


class Limits(StrictModel):
    timeout_seconds: int = Field(default=1800, ge=1, le=3600)
    max_output_tokens: int = Field(default=8000, ge=1, le=8000)


class CodingRequest(Versioned):
    repository: str
    task: str = Field(min_length=1, max_length=50000)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=50)
    base_ref: str = Field(default="HEAD", pattern=r"^[A-Za-z0-9_./-]+$", max_length=200)
    constraints: list[str] = Field(default_factory=list)
    verification_profile: str
    limits: Limits = Field(default_factory=Limits)
    client_request_id: str | None = Field(default=None, min_length=1, max_length=200)
    retry_of: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class Handoff(Versioned):
    task_id: str = Field(min_length=1, max_length=100)
    revision: int = Field(ge=1)
    task_status: Literal["blocked", "completed"]
    blocker_type: Literal[
        "technical_uncertainty",
        "expertise_gap",
        "sensitive",
        "ambiguous",
        "permission_denied",
        "safety_boundary",
    ]
    role: Literal["security_researcher"] = "security_researcher"
    scope_id: str
    objective: str = Field(min_length=1, max_length=30000)
    attempted_approaches: list[str] = Field(default_factory=list)
    verified_findings: list[str] = Field(default_factory=list)
    open_hypotheses: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(min_length=1)
    context: Context = Field(default_factory=Context)
    action: Literal["passive_analysis"] = "passive_analysis"


class Envelope(Versioned):
    request_id: str
    status: str
    data: dict[str, Any] | None = None
    usage: Usage = Field(default_factory=Usage)
    error: dict[str, Any] | None = None
