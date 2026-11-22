from dataclasses import dataclass
import json
from time import monotonic
from typing import Any, Protocol
from uuid import uuid4

from fastapi import HTTPException
from jsonschema import Draft202012Validator
from openai import OpenAI

from .provider_registry import CredentialCipher, get_model_credential


@dataclass(frozen=True)
class ModelRequest:
    instructions: str
    input_payload: dict[str, Any]
    available_tools: tuple[dict[str, Any], ...]
    organization_id: str | None = None
    run_id: str | None = None


@dataclass(frozen=True)
class ModelDecision:
    tool_id: str
    arguments: dict[str, Any]
    explanation: str


class ModelProvider(Protocol):
    """The stable boundary every hosted or local model provider must implement."""

    def decide(self, request: ModelRequest) -> ModelDecision: ...


class DeterministicEstateFlowProvider:
    """Repeatable local provider used to validate orchestration without paid model calls."""

    def decide(self, request: ModelRequest) -> ModelDecision:
        if "native_slot_id" in request.input_payload:
            from .calendar_workflow import is_native_reservation
            tool = next((item for item in request.available_tools if is_native_reservation(item)), None)
            arguments = request.input_payload.get("calendar_slot")
            if tool is None or not isinstance(arguments, dict):
                raise HTTPException(409, "Native scheduling requires an offered slot and exact tool permission.")
            return ModelDecision(str(tool["tool_id"]), dict(arguments),
                                 "Reserve the exact offered slot selected for this viewing.")
        tool = next(
            (item for item in sorted(request.available_tools,
                key=lambda item: "property_id" in item["input_schema"].get("properties", {}),
                reverse=True) if item["name"] == "book_viewing"),
            None,
        )
        if tool is None:
            raise HTTPException(409, "This run has no book_viewing tool permission.")
        customer = request.input_payload.get("customer")
        slot = request.input_payload.get("slot")
        if not isinstance(customer, str) or not customer.strip():
            raise HTTPException(422, "Workflow input requires a non-empty customer.")
        if not isinstance(slot, str) or not slot.strip():
            raise HTTPException(422, "Workflow input requires a non-empty slot.")
        arguments = {"customer": customer.strip(), "slot": slot.strip()}
        if "property_id" in tool["input_schema"].get("properties", {}):
            recommendations = request.input_payload.get("property_recommendations", [])
            if not recommendations:
                raise HTTPException(409, "Property-bound booking requires retrieval evidence.")
            selected = recommendations[0]["property"]
            arguments.update(property_id=str(selected["property_id"]),
                             property_version=selected["current_version"])
        return ModelDecision(
            tool_id=str(tool["tool_id"]),
            arguments=arguments,
            explanation="The structured request contains the customer and requested slot.",
        )


class OpenAIResponsesProvider:
    def __init__(self, api_key: str, model_id: str, timeout_seconds: int,
                 client_factory=OpenAI):
        self.model_id = model_id
        self.client = client_factory(
            api_key=api_key, timeout=timeout_seconds, max_retries=0
        )
        self.last_metadata: dict[str, Any] = {}

    def decide(self, request: ModelRequest) -> ModelDecision:
        tools = [{
            "tool_id": tool["tool_id"], "name": tool["name"],
            "version": tool["version"], "description": tool["description"],
            "input_schema": tool["input_schema"],
        } for tool in request.available_tools]
        response = self.client.responses.create(
            model=self.model_id,
            instructions=request.instructions,
            input=json.dumps({"request": request.input_payload, "available_tools": tools}),
            text={"format": {
                "type": "json_schema",
                "name": "sentinel_tool_decision",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "tool_id": {"type": "string"},
                        "arguments": {"type": "object"},
                        "explanation": {"type": "string"},
                    },
                    "required": ["tool_id", "arguments", "explanation"],
                    "additionalProperties": False,
                },
            }},
            max_output_tokens=500,
            store=False,
        )
        payload = json.loads(response.output_text)
        usage = getattr(response, "usage", None)
        self.last_metadata = {
            "provider_response_id": getattr(response, "id", None),
            "input_tokens": getattr(usage, "input_tokens", 0) if usage else 0,
            "output_tokens": getattr(usage, "output_tokens", 0) if usage else 0,
            "total_tokens": getattr(usage, "total_tokens", 0) if usage else 0,
        }
        return ModelDecision(
            tool_id=payload["tool_id"],
            arguments=payload["arguments"],
            explanation=payload["explanation"],
        )


def validate_decision(decision: ModelDecision, request: ModelRequest) -> None:
    tool = next(
        (item for item in request.available_tools
         if str(item["tool_id"]) == decision.tool_id),
        None,
    )
    if tool is None:
        raise ValueError("Model selected a tool outside the run's frozen permissions.")
    errors = list(Draft202012Validator(tool["input_schema"]).iter_errors(decision.arguments))
    if errors:
        raise ValueError("Model arguments violate the tool contract.")
    if not isinstance(decision.explanation, str) or not decision.explanation.strip():
        raise ValueError("Model decision has no explanation.")


class ModelGateway:
    def __init__(self, providers: dict[str, ModelProvider] | None = None, *,
                 database=None, cipher: CredentialCipher | None = None,
                 timeout_seconds: int = 20, client_factory=OpenAI):
        self.providers = providers or {
            "deterministic_estateflow": DeterministicEstateFlowProvider(),
        }
        self.database = database
        self.cipher = cipher
        self.timeout_seconds = timeout_seconds
        self.client_factory = client_factory
        self.fallback = DeterministicEstateFlowProvider()

    def _record(self, request: ModelRequest, model_alias: str, provider: str,
                model_id: str, status: str, duration_ms: int, metadata: dict | None = None,
                error_class: str | None = None) -> None:
        if self.database is None or request.organization_id is None or request.run_id is None:
            return
        metadata = metadata or {}
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO sentinel_model_invocations
                   (invocation_id, run_id, organization_id, model_alias, provider,
                    model_id, status, provider_response_id, input_tokens, output_tokens,
                    total_tokens, duration_ms, error_class)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (uuid4(), request.run_id, request.organization_id, model_alias, provider,
                 model_id, status, metadata.get("provider_response_id"),
                 metadata.get("input_tokens", 0), metadata.get("output_tokens", 0),
                 metadata.get("total_tokens", 0), duration_ms, error_class),
            )

    def decide(self, model_alias: str, request: ModelRequest) -> ModelDecision:
        started = monotonic()
        provider = self.providers.get(model_alias)
        if provider is not None:
            decision = provider.decide(request)
            validate_decision(decision, request)
            self._record(
                request, model_alias, "deterministic", model_alias, "succeeded",
                int((monotonic() - started) * 1000),
            )
            return decision
        if self.database is None or self.cipher is None or request.organization_id is None:
            raise HTTPException(409, f"No model provider is configured for alias '{model_alias}'.")
        credential = get_model_credential(
            self.database, self.cipher, request.organization_id, model_alias
        )
        hosted = OpenAIResponsesProvider(
            credential["api_key"], credential["model_id"], self.timeout_seconds,
            self.client_factory,
        )
        try:
            decision = hosted.decide(request)
            validate_decision(decision, request)
        except Exception as error:
            try:
                decision = self.fallback.decide(request)
                validate_decision(decision, request)
            except Exception:
                self._record(
                    request, model_alias, "openai", credential["model_id"], "failed",
                    int((monotonic() - started) * 1000), error_class=type(error).__name__,
                )
                raise HTTPException(502, "Hosted model failed and fallback was unavailable.") from error
            self._record(
                request, model_alias, "openai", credential["model_id"], "fallback",
                int((monotonic() - started) * 1000), error_class=type(error).__name__,
            )
            return ModelDecision(
                decision.tool_id, decision.arguments,
                "Deterministic fallback: " + decision.explanation,
            )
        self._record(
            request, model_alias, "openai", credential["model_id"], "succeeded",
            int((monotonic() - started) * 1000), hosted.last_metadata,
        )
        return decision
