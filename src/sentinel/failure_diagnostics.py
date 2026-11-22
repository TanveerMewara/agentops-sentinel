"""Deterministic failure diagnosis from bounded, structured agent evidence.

The detector intentionally does not inspect prompts, tool arguments, responses, or
exception text.  Integrations normalize those private values into the small set of
signals below before requesting a diagnosis.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping


FailureCategory = Literal[
    "no_failure",
    "tool_execution_failure",
    "timeout",
    "invalid_tool_arguments",
    "malformed_llm_output",
    "hallucinated_unsupported_response",
    "api_failure",
    "retry_exhaustion",
    "routing_failure",
    "retrieval_failure",
    "validation_failure",
]

FAILURE_CATEGORIES: tuple[FailureCategory, ...] = (
    "no_failure",
    "tool_execution_failure",
    "timeout",
    "invalid_tool_arguments",
    "malformed_llm_output",
    "hallucinated_unsupported_response",
    "api_failure",
    "retry_exhaustion",
    "routing_failure",
    "retrieval_failure",
    "validation_failure",
)


@dataclass(frozen=True, slots=True)
class FailureObservation:
    tool_status: Literal["completed", "failed"] = "completed"
    timed_out: bool = False
    tool_arguments_valid: bool = True
    llm_output_valid: bool = True
    response_supported: bool = True
    api_status: int = 200
    retry_exhausted: bool = False
    route_valid: bool = True
    retrieval_sufficient: bool = True
    validation_passed: bool = True

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "FailureObservation":
        allowed = set(cls.__dataclass_fields__)
        unknown = set(value) - allowed
        if unknown:
            raise ValueError("Failure observation contains unsupported signals.")
        booleans = allowed - {"tool_status", "api_status"}
        if any(name in value and type(value[name]) is not bool for name in booleans):
            raise ValueError("Failure observation flags must be booleans.")
        tool_status = value.get("tool_status", "completed")
        if tool_status not in ("completed", "failed"):
            raise ValueError("Tool status is invalid.")
        api_status = value.get("api_status", 200)
        if type(api_status) is not int or not 100 <= api_status <= 599:
            raise ValueError("API status must be an HTTP status code.")
        return cls(**value)


@dataclass(frozen=True, slots=True)
class FailureDiagnosis:
    category: FailureCategory
    rule: str
    failed: bool

    def as_dict(self) -> dict[str, object]:
        return {"category": self.category, "rule": self.rule, "failed": self.failed}


def diagnose(observation: FailureObservation) -> FailureDiagnosis:
    """Return one primary category using a documented, stable precedence.

    The benchmark corpus isolates one primary fault per scenario.  Precedence makes
    real multi-signal observations deterministic and is part of the detector version.
    """
    checks: tuple[tuple[bool, FailureCategory, str], ...] = (
        (observation.timed_out, "timeout", "timeout_observed"),
        (not observation.tool_arguments_valid, "invalid_tool_arguments", "tool_contract_rejected"),
        (not observation.llm_output_valid, "malformed_llm_output", "llm_contract_rejected"),
        (not observation.response_supported, "hallucinated_unsupported_response", "support_evidence_missing"),
        (observation.api_status >= 400, "api_failure", "upstream_http_failure"),
        (observation.retry_exhausted, "retry_exhaustion", "bounded_retry_budget_exhausted"),
        (not observation.route_valid, "routing_failure", "route_resolution_failed"),
        (not observation.retrieval_sufficient, "retrieval_failure", "retrieval_evidence_insufficient"),
        (not observation.validation_passed, "validation_failure", "output_validation_failed"),
        (observation.tool_status == "failed", "tool_execution_failure", "tool_reported_failure"),
    )
    for matched, category, rule in checks:
        if matched:
            return FailureDiagnosis(category, rule, True)
    return FailureDiagnosis("no_failure", "no_failure_signal", False)


DETECTOR_VERSION = "structured_rules_v1"
