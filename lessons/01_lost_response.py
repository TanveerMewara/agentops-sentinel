"""Run with: python lessons/01_lost_response.py

An in-memory teaching experiment, not the production execution layer.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Booking:
    booking_id: str
    customer: str
    slot: str


class BookingService:
    """Pretend this object is a separate appointment-booking service."""

    def __init__(self) -> None:
        self.bookings: list[Booking] = []
        self.operations: dict[str, Booking] = {}

    def create_booking(
        self,
        customer: str,
        slot: str,
        *,
        operation_id: str | None = None,
        lose_response: bool = False,
    ) -> Booking:
        if operation_id is not None and operation_id in self.operations:
            existing = self.operations[operation_id]
            if (existing.customer, existing.slot) != (customer, slot):
                raise ValueError("An operation ID cannot be reused with changed details.")
            print(f"  SERVICE: operation already completed; returning {existing.booking_id}.")
            return existing

        booking = Booking(f"booking-{len(self.bookings) + 1}", customer, slot)
        self.bookings.append(booking)
        if operation_id is not None:
            self.operations[operation_id] = booking
        print(f"  SERVICE: created {booking.booking_id}.")

        # The booking exists BEFORE the caller receives an error.
        if lose_response:
            raise TimeoutError("The response was lost after the booking was created.")
        return booking


def run_scenario(*, use_operation_id: bool) -> BookingService:
    service = BookingService()
    # This identifies one intended action, and stays the same across its retries.
    operation_id = "viewing-request-001" if use_operation_id else None
    print("\nWITH an operation ID" if use_operation_id else "WITHOUT an operation ID")

    try:
        service.create_booking(
            "Asha", "2030-01-15 10:00", operation_id=operation_id, lose_response=True
        )
    except TimeoutError:
        print("  CALLER: received a timeout. I do not know whether the booking exists.")
        print("  CALLER: retrying the same intended action.")
        result = service.create_booking(
            "Asha", "2030-01-15 10:00", operation_id=operation_id
        )
        print(f"  CALLER: received {result.booking_id}.")

    print(f"  Actual appointments in the service: {len(service.bookings)}")
    return service


def main() -> None:
    unsafe = run_scenario(use_operation_id=False)
    protected = run_scenario(use_operation_id=True)

    # Verify external state, not just the caller's final response.
    assert len(unsafe.bookings) == 2, "The baseline should expose a duplicate."
    assert len(protected.bookings) == 1, "Retry should reuse the existing booking."

    try:
        protected.create_booking(
            "Asha", "2030-01-15 11:00", operation_id="viewing-request-001"
        )
    except ValueError:
        print("\nCHECK: changed details with the same operation ID were rejected.")
    else:
        raise AssertionError("Changed action details must not silently reuse an ID.")

    assert len(protected.bookings) == 1
    print("CHECKS PASSED: duplicate reproduced, retry deduplicated, changed details rejected.")


if __name__ == "__main__":
    main()
