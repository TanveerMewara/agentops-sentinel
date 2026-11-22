"""Lesson 5: one HTTP submission, then read-only reconciliation. No persistence."""
import argparse
from dataclasses import dataclass
import importlib
import json
from urllib.parse import quote
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

states = importlib.import_module("lessons.04_operation_states")
Operation, State, Event, advance = states.Operation, states.State, states.Event, states.advance


@dataclass(frozen=True)
class Action:
    operation_id: str
    customer: str
    slot: str


class BookingAdapter:
    """Translate this specific service's replies into checked evidence."""
    def __init__(self, base_url: str, *, supports_lookup: bool = True):
        self.base_url = base_url.rstrip("/")
        self.supports_lookup = supports_lookup
        self.opener = build_opener(ProxyHandler({}))
        self.submissions = 0
        self.lookups = 0

    def request(self, path, payload=None, timeout=3):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(self.base_url + path, data=data,
                          headers={"Content-Type": "application/json"},
                          method="GET" if payload is None else "POST")
        with self.opener.open(request, timeout=timeout) as response:
            if response.status != 200:
                raise ValueError("Unexpected response status")
            return json.load(response)

    def submit(self, action: Action, delay: float):
        self.submissions += 1
        return self.request("/operations", {
            "operation_id": action.operation_id, "customer": action.customer,
            "slot": action.slot, "response_delay_seconds": delay,
        }, timeout=0.5)

    def lookup(self, action: Action):
        if not self.supports_lookup:
            raise ValueError("This adapter has no trustworthy operation lookup.")
        self.lookups += 1
        return self.request("/operations/" + quote(action.operation_id, safe=""))

    @staticmethod
    def confirmed_booking(action: Action, receipt) -> str:
        if not isinstance(receipt, dict):
            raise ValueError("Receipt must be an object.")
        for field in ("operation_id", "customer", "slot"):
            if receipt.get(field) != getattr(action, field):
                raise ValueError(f"Receipt does not match requested {field}.")
        booking_id = receipt.get("booking_id")
        if not isinstance(booking_id, str) or not booking_id.strip():
            raise ValueError("Receipt has no valid booking ID.")
        return booking_id


def execute_once(action: Action, adapter: BookingAdapter, *, delay: float = 2) -> Operation:
    operation = advance(Operation(action.operation_id), Event.START)
    try:
        receipt = adapter.submit(action, delay)
        booking_id = adapter.confirmed_booking(action, receipt)
    except TimeoutError:
        operation = advance(operation, Event.TIMEOUT)
    except (OSError, ValueError):
        # HTTP errors, broken connections, and invalid replies do not prove no effect.
        operation = advance(operation, Event.OUTCOME_UNCERTAIN)
    else:
        return advance(operation, Event.CONFIRMED_SUCCESS, booking_id=booking_id)

    # There is deliberately no second POST anywhere in this function.
    try:
        receipt = adapter.lookup(action)
        booking_id = adapter.confirmed_booking(action, receipt)
    except (OSError, ValueError):
        # Includes 404: not seeing a result does not prove the original cannot finish.
        return advance(operation, Event.CANNOT_VERIFY)
    return advance(operation, Event.CONFIRMED_SUCCESS, booking_id=booking_id)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8002")
    parser.add_argument("--no-lookup", action="store_true",
                        help="Model a service adapter with no trustworthy lookup capability.")
    args = parser.parse_args()
    adapter = BookingAdapter(args.base_url, supports_lookup=not args.no_lookup)
    # Fail early if the teaching server is absent; do not mistake that for a demo success.
    try:
        adapter.request("/health")
    except OSError as error:
        raise SystemExit("Start lessons.reconciliation_service on port 8002 first.") from error
    action = Action(uuid4().hex, "Asha", "2030-01-15 10:00")
    result = execute_once(action, adapter)
    print("Operation:", result.operation_id)
    for entry in result.history:
        print(" ", entry)
    print("Final state:", result.state.value)
    print("Booking ID:", result.booking_id)
    print(f"Submissions: {adapter.submissions}; read-only lookups: {adapter.lookups}")
    print("This lesson stores Sentinel state and external bookings in memory only.")


if __name__ == "__main__":
    main()
