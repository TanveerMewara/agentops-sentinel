"""Lesson 2: local teaching API. All records disappear when it stops."""

import asyncio

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field


class BookingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    customer: str = Field(min_length=1, max_length=100)
    slot: str = Field(min_length=1, max_length=100)
    operation_id: str | None = Field(default=None, min_length=1, max_length=100)
    # Teaching-only fault injection, not a production API feature.
    response_delay_seconds: float = Field(default=0, ge=0, le=5)


class Booking(BaseModel):
    booking_id: str
    customer: str
    slot: str


app = FastAPI(title="Sentinel Lesson 2: Pretend Booking Service")
bookings: list[Booking] = []
operations: dict[str, Booking] = {}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/bookings", response_model=list[Booking])
async def list_bookings() -> list[Booking]:
    return bookings


@app.post("/bookings", response_model=Booking)
async def create_booking(request: BookingRequest) -> Booking:
    if request.operation_id is not None and request.operation_id in operations:
        existing = operations[request.operation_id]
        if (existing.customer, existing.slot) != (request.customer, request.slot):
            raise HTTPException(status_code=409, detail="Operation ID already used with different details.")
        return existing

    booking = Booking(
        booking_id=f"booking-{len(bookings) + 1}",
        customer=request.customer,
        slot=request.slot,
    )
    bookings.append(booking)
    if request.operation_id is not None:
        operations[request.operation_id] = booking

    # Save BEFORE delaying the reply. A client timeout does not undo this action.
    await asyncio.sleep(request.response_delay_seconds)
    return booking
