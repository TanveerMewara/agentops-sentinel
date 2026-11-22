import json
import math
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import ProxyHandler, Request, build_opener

from .client import NoRedirect, validate_api_url
from .provider_circuit import CircuitOpen, ProviderCircuit


class UncertainOutcome(Exception):
    def __init__(self, message="", *, retryable_read=False):
        super().__init__(message)
        self.retryable_read = retryable_read


class EvidenceMismatch(Exception):
    pass


class BookingAdapter:
    def __init__(self, base_url: str, *, recovery_attempts: int = 3, sleeper=time.sleep,
                 circuit=None):
        if type(recovery_attempts) is not int or not 1 <= recovery_attempts <= 3:
            raise ValueError("Recovery attempts must be between one and three.")
        self.base_url = validate_api_url(base_url)
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        self.recovery_attempts = recovery_attempts
        self.sleeper = sleeper
        self.circuit = circuit if circuit is not None else ProviderCircuit()

    def _probe(self):
        response = self._request("/health")
        if not isinstance(response, dict) or response.get("status") != "ok":
            raise UncertainOutcome("Booking health could not be confirmed.")

    def prepare_execution(self):
        from fastapi import HTTPException
        try:
            self.circuit.before_write(self._probe)
        except CircuitOpen:
            raise HTTPException(503, "Booking provider is temporarily unavailable.",
                                headers={"Retry-After": str(math.ceil(self.circuit.cooldown))}) from None

    def _request(self, path: str, payload: dict | None = None, timeout: float = 3):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="GET" if payload is None else "POST",
        )
        try:
            with self.opener.open(request, timeout=timeout) as response:
                return json.load(response)
        except (TimeoutError, HTTPError, URLError, OSError, ValueError) as error:
            if isinstance(error, HTTPError):
                retryable = error.code in (408, 425, 429) or error.code >= 500
                error.close()
            else:
                retryable = isinstance(error, (TimeoutError, URLError, OSError))
            if retryable:
                self.circuit.record_failure()
            raise UncertainOutcome(type(error).__name__, retryable_read=retryable) from None

    @staticmethod
    def validate(operation_id: str, action: dict, receipt: dict) -> str:
        expected = {
            "operation_id": operation_id,
            "customer": action["customer"],
            "slot": action["slot"],
        }
        if "property_id" in action:
            expected.update(property_id=action["property_id"], property_version=action["property_version"])
        if not isinstance(receipt, dict) or any(receipt.get(k) != v for k, v in expected.items()):
            raise EvidenceMismatch("Receipt does not match the authorized action.")
        booking_id = receipt.get("booking_id")
        if not isinstance(booking_id, str) or not booking_id.strip():
            raise EvidenceMismatch("Receipt has no booking ID.")
        return booking_id

    def execute(self, operation_id: str, action: dict) -> str:
        try:
            self.circuit.before_write(self._probe)
        except CircuitOpen:
            # The circuit can open after the ledger claim. Preserve uncertainty
            # rather than permitting an automatic repeat of the claimed action.
            raise UncertainOutcome("Booking dispatch was paused by the provider circuit.") from None
        receipt = self._request(
            "/operations",
            {"operation_id": operation_id, **action, "response_delay_seconds": 0},
        )
        external_id = self.validate(operation_id, action, receipt)
        self.circuit.record_success()
        return external_id

    def reconcile(self, operation_id: str, action: dict) -> str:
        for attempt in range(self.recovery_attempts):
            try:
                receipt = self._request("/operations/" + quote(operation_id, safe=""))
                external_id = self.validate(operation_id, action, receipt)
                self.circuit.record_success()
                return external_id
            except UncertainOutcome as error:
                if not error.retryable_read or attempt + 1 == self.recovery_attempts:
                    raise
                self.sleeper(0.1 * (2 ** attempt))
