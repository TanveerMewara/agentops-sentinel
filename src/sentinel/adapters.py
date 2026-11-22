"""Deployment-installed adapters; registration never supplies executable code."""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from typing import Protocol

from fastapi import HTTPException
from .booking_adapter import BookingAdapter, EvidenceMismatch, UncertainOutcome


@dataclass(frozen=True)
class AdapterContext:
    organization_id: str
    run_id: str
    tool_call_id: str
    arguments: dict
    contract: dict


@dataclass(frozen=True)
class AdapterResult:
    external_id: str
    result: dict


class ToolAdapter(Protocol):
    def execute(self, context: AdapterContext) -> AdapterResult: ...
    def reconcile(self, context: AdapterContext) -> AdapterResult: ...


def contract_digest(contract):
    fields = {key: contract[key] for key in
              ("name", "version", "input_schema", "output_schema", "risk_level", "approval_mode")}
    return hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class BookingToolAdapter:
    def __init__(self, booking):
        self.booking = booking

    def prepare_execution(self):
        prepare = getattr(self.booking, "prepare_execution", None)
        if callable(prepare):
            prepare()

    def execute(self, context):
        external_id = self.booking.execute(context.tool_call_id, context.arguments)
        return AdapterResult(external_id, {"booking_id": external_id})

    def reconcile(self, context):
        external_id = self.booking.reconcile(context.tool_call_id, context.arguments)
        return AdapterResult(external_id, {"booking_id": external_id})


class AdapterRegistry:
    def __init__(self, booking=None):
        self._installed = {}
        self._contracts = []
        self._booking = BookingToolAdapter(booking) if booking is not None else None

    def install(self, contract, adapter: ToolAdapter):
        # Installation is Python deployment code, never an HTTP capability.
        from .schemas import ToolCreate
        validated = ToolCreate.model_validate(contract).model_dump()
        key = (validated["name"], validated["version"])
        if key in self._installed or key[0] == "book_viewing":
            raise ValueError("Adapter contract is already installed or reserved.")
        if not callable(getattr(adapter, "execute", None)) or not callable(getattr(adapter, "reconcile", None)):
            raise ValueError("Adapters require execution and read-only reconciliation.")
        self._installed[key] = (contract_digest(validated), adapter)
        self._contracts.append({field: deepcopy(validated[field]) for field in
                               ("name", "version", "input_schema", "output_schema", "risk_level", "approval_mode")})

    def discovery_filters(self):
        filters = deepcopy(self._contracts)
        if self._booking is not None:
            filters += [{"name": "book_viewing", "version": version, "risk_level": "high", "approval_mode": "always"}
                        for version in ("1.0.0", "2.0.0")]
        return filters

    def resolve(self, contract):
        key = (contract["name"], contract["version"])
        if (self._booking is not None and key in (("book_viewing", "1.0.0"), ("book_viewing", "2.0.0"))
                and contract["risk_level"] == "high" and contract["approval_mode"] == "always"):
            return self._booking
        installed = self._installed.get(key)
        if installed is None or installed[0] != contract_digest(contract):
            raise HTTPException(501, "No matching deployment-installed adapter exists for this contract.")
        return installed[1]

    def booking_circuit_snapshot(self):
        from .provider_circuit import ProviderCircuit
        circuit = getattr(self._booking.booking, "circuit", None) if self._booking is not None else None
        return circuit.snapshot() if isinstance(circuit, ProviderCircuit) else None

    def prepare_execution(self, contract):
        adapter = self.resolve(contract)
        prepare = getattr(adapter, "prepare_execution", None)
        if callable(prepare):
            prepare()

    def supports(self, contract):
        try:
            self.resolve(contract)
            return True
        except (HTTPException, KeyError):
            return False

    def invoke(self, method, call, principal):
        adapter = self.resolve(call["contract_snapshot"])
        context = AdapterContext(str(principal.organization_id), str(call["run_id"]),
            str(call["tool_call_id"]), deepcopy(call["arguments"]), deepcopy(call["contract_snapshot"]))
        try:
            outcome = getattr(adapter, method)(context)
            if (not isinstance(outcome, AdapterResult) or not isinstance(outcome.result, dict)
                    or not isinstance(outcome.external_id, str) or not outcome.external_id.strip()
                    or len(outcome.external_id) > 500):
                raise EvidenceMismatch("Adapter returned invalid evidence.")
            return outcome
        except (UncertainOutcome, EvidenceMismatch):
            raise
        except Exception:
            # An arbitrary adapter exception may occur after an external write.
            # Never expose its message or treat it as permission to repeat.
            raise UncertainOutcome("Adapter result could not be confirmed.") from None


def registry_for(adapter):
    return adapter if isinstance(adapter, AdapterRegistry) else AdapterRegistry(booking=adapter)
