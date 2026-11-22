from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


class BookingAction(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    customer: str = Field(min_length=1, max_length=100)
    slot: str = Field(min_length=1, max_length=100)


class OperationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    idempotency_key: str = Field(min_length=8, max_length=200)
    action_type: Literal["book_viewing"]
    action: BookingAction


class OperationView(BaseModel):
    operation_id: UUID
    idempotency_key: str
    action_type: str
    action: dict[str, Any]
    status: str
    external_id: str | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class ApprovalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    valid_for_seconds: int = Field(default=300, ge=30, le=3600)


class ApprovalView(BaseModel):
    approval_id: UUID
    operation_id: UUID
    state: str
    expires_at: datetime


class EventView(BaseModel):
    event_id: int
    event_type: str
    from_status: str | None
    to_status: str
    details: dict[str, Any]
    created_at: datetime


class AgentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    slug: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    display_name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)


class AgentView(BaseModel):
    agent_id: UUID
    slug: str
    display_name: str
    description: str
    status: Literal["active", "disabled"]
    created_at: datetime
    updated_at: datetime


class ToolCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    description: str = Field(min_length=1, max_length=500)
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    risk_level: Literal["low", "medium", "high"]
    approval_mode: Literal["never", "risk_based", "always"]

    @model_validator(mode="after")
    def validate_contract(self):
        for label, schema in (
            ("input_schema", self.input_schema),
            ("output_schema", self.output_schema),
        ):
            if schema.get("type") != "object" or not isinstance(schema.get("properties"), dict):
                raise ValueError(f"{label} must be a JSON object schema with properties.")
            if schema.get("additionalProperties") is not False:
                raise ValueError(f"{label} must set additionalProperties to false.")
            required = schema.get("required", [])
            if (not isinstance(required, list)
                    or len(required) != len(set(required))
                    or any(name not in schema["properties"] for name in required)):
                raise ValueError(f"{label}.required must uniquely name declared properties.")
            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError as error:
                raise ValueError(f"{label} is not a valid JSON Schema: {error.message}") from error
            if _contains_remote_reference(schema):
                raise ValueError(f"{label} cannot contain remote $ref values.")
        if self.risk_level == "high" and self.approval_mode != "always":
            raise ValueError("High-risk tools must always require approval.")
        return self


def _contains_remote_reference(value: Any) -> bool:
    if isinstance(value, dict):
        reference = value.get("$ref")
        if isinstance(reference, str) and not reference.startswith("#"):
            return True
        return any(_contains_remote_reference(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_remote_reference(item) for item in value)
    return False


class ToolView(BaseModel):
    tool_id: UUID
    name: str
    version: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    risk_level: Literal["low", "medium", "high"]
    approval_mode: Literal["never", "risk_based", "always"]
    status: Literal["active", "disabled"]
    created_at: datetime
    updated_at: datetime


class AgentToolGrantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_calls_per_run: int = Field(default=1, ge=1, le=100)


class AgentToolGrantView(BaseModel):
    agent_id: UUID
    tool_id: UUID
    max_calls_per_run: int
    granted_at: datetime


class RegistryEventView(BaseModel):
    event_id: int
    resource_type: str
    resource_id: UUID
    event_type: str
    details: dict[str, Any]
    created_at: datetime


class AgentVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    instructions: str = Field(min_length=1, max_length=20000)
    model_alias: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,63}$")
    max_steps: int = Field(default=12, ge=1, le=100)


class AgentVersionView(BaseModel):
    agent_version_id: UUID
    agent_id: UUID
    version: str
    instructions: str
    model_alias: str
    max_steps: int
    created_at: datetime


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    idempotency_key: str = Field(min_length=8, max_length=200)
    agent_version_id: UUID
    input: dict[str, Any]


class RunView(BaseModel):
    run_id: UUID
    agent_id: UUID
    agent_version_id: UUID
    idempotency_key: str
    input: dict[str, Any]
    status: Literal["queued", "running", "succeeded", "failed", "cancelled", "needs_review"]
    max_steps: int
    steps_used: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime


class ToolCallReserve(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    idempotency_key: str = Field(min_length=8, max_length=200)
    tool_id: UUID
    arguments: dict[str, Any]


class ToolCallView(BaseModel):
    tool_call_id: UUID
    run_id: UUID
    tool_id: UUID
    idempotency_key: str
    sequence: int
    arguments: dict[str, Any]
    status: Literal[
        "reserved", "awaiting_approval", "authorized", "executing", "unknown",
        "completed", "failed", "cancelled", "needs_review",
    ]
    requires_approval: bool
    result: dict[str, Any] | None
    error: str | None
    external_id: str | None
    created_at: datetime
    completed_at: datetime | None


class ToolCallApprovalView(BaseModel):
    approval_id: UUID
    tool_call_id: UUID
    state: Literal["approved", "consumed", "revoked"]
    expires_at: datetime


class RunEventView(BaseModel):
    event_id: int
    event_type: str
    details: dict[str, Any]
    created_at: datetime


class WorkflowView(BaseModel):
    run_id: UUID
    thread_id: str
    status: Literal[
        "not_started", "planning", "no_match", "reserving_tool", "waiting_approval",
        "executing", "completed", "unknown", "needs_review", "rejected",
        "lead_not_ready", "slot_unavailable",
    ]
    model_alias: str | None
    lead_id: UUID | None = None
    lead_version: int | None = None
    retrieval_id: UUID | None = None
    recommendations: list["PropertySearchResult"] = Field(default_factory=list)
    tool_call_id: UUID | None
    model_explanation: str | None
    result: dict[str, Any] | None
    crm_contact_id: UUID | None = None
    followup_draft_id: UUID | None = None


class LeadUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    external_key: str = Field(min_length=1, max_length=120)
    channel: Literal["manual", "website"] = "manual"
    customer_name: str = Field(min_length=1, max_length=100)
    contact_email: str | None = Field(default=None, min_length=3, max_length=254)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    max_budget_inr: Decimal | None = Field(
        default=None, gt=0, max_digits=16, decimal_places=2
    )
    min_bedrooms: int | None = Field(default=None, ge=0, le=20)
    timeline: Literal["unknown", "within_month", "within_quarter", "later"] = "unknown"
    outreach_consent: bool = False
    human_help_requested: bool = False

    @field_validator("contact_email")
    @classmethod
    def valid_contact_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        local, separator, domain = value.partition("@")
        if not separator or not local or "." not in domain or any(
            character.isspace() for character in value
        ):
            raise ValueError("contact_email must be a valid-looking email address.")
        return value.lower()


class LeadView(LeadUpsert):
    lead_id: UUID
    qualification_status: Literal[
        "needs_information", "qualified", "nurture", "human_review"
    ]
    qualification_reasons: list[str]
    current_version: int
    created_at: datetime
    updated_at: datetime


class LeadUpsertOutcome(BaseModel):
    lead: LeadView
    outcome: Literal["created", "updated", "unchanged"]


class EnquiryDeliveryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    delivery_key: str = Field(min_length=8, max_length=200)
    source_sequence: int = Field(gt=0, le=9223372036854775807)
    lead: LeadUpsert

    @model_validator(mode="after")
    def website_only(self):
        if self.lead.channel != "website":
            raise ValueError("Enquiry delivery requires channel website.")
        return self


class EnquiryDeliveryView(BaseModel):
    delivery_id: UUID
    delivery_key: str
    source_sequence: int
    lead_id: UUID
    lead_version: int
    qualification_status: str
    outcome: Literal["created", "updated", "unchanged"]


class LeadRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    idempotency_key: str = Field(min_length=8, max_length=200)
    agent_version_id: UUID
    slot: str | None = Field(default=None, min_length=1, max_length=100)
    native_slot_id: UUID | None = None
    property_query: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def exactly_one_slot(self):
        if (self.slot is None) == (self.native_slot_id is None):
            raise ValueError("Supply either a legacy viewing time or a native slot ID.")
        return self


class LeadHandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason_code: Literal[
        "customer_requested", "complex_requirements", "agent_uncertain", "other"
    ]


class LeadReviewResolve(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolution_code: Literal["answered_questions", "requirements_confirmed"]


class LeadVersionView(BaseModel):
    lead_version_id: UUID
    lead_id: UUID
    version: int
    content_hash: str
    requirements: dict[str, Any]
    qualification_status: str
    qualification_reasons: list[str]
    created_at: datetime


class LeadEventView(BaseModel):
    event_id: int
    event_type: str
    details: dict[str, Any]
    created_at: datetime


class CRMContactView(BaseModel):
    crm_contact_id: UUID
    lead_id: UUID
    stage: Literal["qualified", "viewing_booked", "nurture", "human_review"]
    last_run_id: UUID | None
    booking_id: str | None
    selected_property_id: UUID | None
    created_at: datetime
    updated_at: datetime


class FollowupDraftView(BaseModel):
    draft_id: UUID
    lead_id: UUID
    run_id: UUID
    channel: Literal["email"]
    status: Literal["draft", "approved", "cancelled"]
    revision: int
    recipient: str
    subject: str
    body: str
    context_snapshot: dict[str, Any]
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class FollowupDraftEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=1)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=10000)


class FollowupDraftApprove(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)


class OpenAIProviderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    model_alias: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,63}$")
    model_id: str = Field(min_length=1, max_length=100)
    api_key: SecretStr = Field(min_length=20, max_length=500)


class ModelProviderView(BaseModel):
    provider_id: UUID
    model_alias: str
    provider: Literal["openai"]
    model_id: str
    key_hint: str
    status: Literal["active", "disabled"]
    created_at: datetime
    updated_at: datetime


class ModelInvocationView(BaseModel):
    invocation_id: UUID
    run_id: UUID
    model_alias: str
    provider: str
    model_id: str
    status: Literal["succeeded", "fallback", "failed"]
    provider_response_id: str | None
    input_tokens: int
    output_tokens: int
    total_tokens: int
    duration_ms: int
    error_class: str | None
    created_at: datetime


class PropertyUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    external_key: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=5000)
    city: str = Field(min_length=1, max_length=100)
    locality: str = Field(min_length=1, max_length=150)
    property_type: Literal["apartment", "house", "villa", "plot", "commercial"]
    bedrooms: int | None = Field(default=None, ge=0, le=20)
    bathrooms: Decimal | None = Field(default=None, ge=0, le=20, decimal_places=1)
    price_inr: Decimal = Field(ge=0, max_digits=16, decimal_places=2)
    area_sqft: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    amenities: list[str] = Field(default_factory=list, max_length=50)
    source_uri: str = Field(min_length=1, max_length=500)
    listing_status: Literal["active", "reserved", "sold", "inactive"] = "active"

    @field_validator("amenities")
    @classmethod
    def normalize_amenities(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().lower() for value in values]
        if any(not value or len(value) > 80 for value in normalized):
            raise ValueError("Amenities must contain 1 to 80 characters.")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Amenities must be unique.")
        return sorted(normalized)

    @field_validator("source_uri")
    @classmethod
    def valid_source_uri(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("source_uri must be an HTTP or HTTPS URL with a host.")
        if parsed.username or parsed.password:
            raise ValueError("source_uri cannot contain credentials.")
        return value


class PropertyBatchUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")
    properties: list[PropertyUpsert] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_external_keys(self):
        keys = [item.external_key for item in self.properties]
        if len(keys) != len(set(keys)):
            raise ValueError("A batch cannot contain duplicate external_key values.")
        return self


class PropertyView(PropertyUpsert):
    property_id: UUID
    current_version: int
    created_at: datetime
    updated_at: datetime


class PropertyUpsertOutcome(BaseModel):
    property: PropertyView
    outcome: Literal["created", "updated", "unchanged"]


class PropertySearch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=500)
    strategy: Literal["lexical", "vector"] = "lexical"
    embedding_model_alias: str = Field(
        default="estate_embeddings", pattern=r"^[a-z][a-z0-9_-]{2,63}$"
    )
    city: str | None = Field(default=None, min_length=1, max_length=100)
    property_type: Literal["apartment", "house", "villa", "plot", "commercial"] | None = None
    min_bedrooms: int | None = Field(default=None, ge=0, le=20)
    max_price_inr: Decimal | None = Field(default=None, ge=0, max_digits=16, decimal_places=2)
    required_amenities: list[str] = Field(default_factory=list, max_length=20)
    limit: int = Field(default=10, ge=1, le=50)

    @field_validator("required_amenities")
    @classmethod
    def normalize_required_amenities(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().lower() for value in values]
        if any(not value or len(value) > 80 for value in normalized):
            raise ValueError("Required amenities must contain 1 to 80 characters.")
        return sorted(set(normalized))


class PropertyEvidence(BaseModel):
    property_version: int
    source_uri: str
    matched_terms: list[str]
    matched_fields: list[str]
    applied_filters: dict[str, Any]
    embedding_id: UUID | None = None
    embedding_model_id: str | None = None
    embedding_source_hash: str | None = None


class PropertySearchResult(BaseModel):
    property: PropertyView
    score: float
    evidence: PropertyEvidence


class PropertySearchResponse(BaseModel):
    retrieval_id: UUID
    strategy: Literal[
        "hybrid_lexical_v1", "vector_array_exact_v1", "vector_pgvector_exact_v1"
    ]
    embedding_model_id: str | None = None
    results: list[PropertySearchResult]


class PropertyVersionView(BaseModel):
    property_version_id: UUID
    property_id: UUID
    version: int
    content_hash: str
    snapshot: dict[str, Any]
    created_at: datetime


class PropertyRetrievalView(BaseModel):
    retrieval_id: UUID
    query_text: str
    filters: dict[str, Any]
    strategy: Literal[
        "hybrid_lexical_v1", "vector_array_exact_v1", "vector_pgvector_exact_v1"
    ]
    embedding_model_alias: str | None = None
    embedding_model_id: str | None = None
    embedding_backend: str | None = None
    result_evidence: list[dict[str, Any]]
    created_at: datetime


WorkflowView.model_rebuild()


class PropertyEmbeddingBackfill(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    model_alias: str = Field(
        default="estate_embeddings", pattern=r"^[a-z][a-z0-9_-]{2,63}$"
    )
    limit: int = Field(default=10, ge=1, le=10)
    external_key_prefix: str | None = Field(default=None, min_length=1, max_length=120)


class PropertyEmbeddingBackfillView(BaseModel):
    model_alias: str
    model_id: str
    embedded: int
    skipped: int
    remaining: int
