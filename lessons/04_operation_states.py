"""Lesson 4: action outcome rules, independent of HTTP and storage.

This is an in-memory teaching model, not a production recovery engine.
Run: python lessons/04_operation_states.py
"""
from dataclasses import dataclass, replace
from enum import Enum


class State(str, Enum):
    READY = "ready"
    EXECUTING = "executing"
    UNKNOWN = "unknown"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


class Event(str, Enum):
    START = "start"
    TIMEOUT = "timeout"
    OUTCOME_UNCERTAIN = "outcome_uncertain"
    CONFIRMED_SUCCESS = "confirmed_success"
    REJECTED_WITHOUT_EFFECT = "rejected_without_effect"
    CANNOT_VERIFY = "cannot_verify"


# Each key is (where we are, what happened); its value is the allowed next state.
TRANSITIONS = {
    (State.READY, Event.START): State.EXECUTING,
    (State.EXECUTING, Event.TIMEOUT): State.UNKNOWN,
    (State.EXECUTING, Event.OUTCOME_UNCERTAIN): State.UNKNOWN,
    (State.EXECUTING, Event.CONFIRMED_SUCCESS): State.SUCCEEDED,
    (State.EXECUTING, Event.REJECTED_WITHOUT_EFFECT): State.FAILED,
    (State.UNKNOWN, Event.CONFIRMED_SUCCESS): State.SUCCEEDED,
    (State.UNKNOWN, Event.CANNOT_VERIFY): State.NEEDS_REVIEW,
}


@dataclass(frozen=True)
class Operation:
    operation_id: str
    state: State = State.READY
    booking_id: str | None = None
    history: tuple[str, ...] = ()


def advance(operation: Operation, event: Event, *, booking_id: str | None = None) -> Operation:
    """Return a new record; reject a transition not covered by our rules."""
    target = TRANSITIONS.get((operation.state, event))
    if target is None:
        raise ValueError(f"Cannot apply {event.value} while operation is {operation.state.value}.")
    if event == Event.CONFIRMED_SUCCESS:
        if not isinstance(booking_id, str) or not booking_id.strip():
            raise ValueError("Confirmed success requires a nonempty booking ID.")
    elif booking_id is not None:
        raise ValueError("Only a confirmed success can attach a booking ID.")
    return replace(
        operation,
        state=target,
        booking_id=booking_id,
        history=operation.history + (f"{operation.state.value} --{event.value}--> {target.value}",),
    )


def main():
    operation = Operation("viewing-request-001")
    operation = advance(operation, Event.START)
    operation = advance(operation, Event.TIMEOUT)
    print("A request timed out. Sentinel's current knowledge:", operation.state.value)

    try:
        advance(operation, Event.START)
    except ValueError as error:
        print("Blind retry blocked:", error)

    # These are alternate simulated outcomes, not two actions on a real service.
    confirmed = advance(operation, Event.CONFIRMED_SUCCESS, booking_id="booking-123")
    unresolved = advance(operation, Event.CANNOT_VERIFY)
    print("\nScenario A: a simulated trustworthy lookup finds the booking.")
    print("Final state:", confirmed.state.value, "Result:", confirmed.booking_id)
    print("\nScenario B: the service cannot establish the outcome.")
    print("Final state:", unresolved.state.value)
    print("\nScenario A history:")
    for entry in confirmed.history:
        print(" ", entry)
    print("\nNo API or database was called. This demonstration tests the decision rules only.")


if __name__ == "__main__":
    main()

