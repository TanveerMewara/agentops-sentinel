"""Lesson 5's local service: Lesson 2 bookings plus operation-specific receipts."""
from fastapi import HTTPException
from pydantic import Field
from lessons.booking_api import app, BookingRequest, create_booking, operations


class OperationRequest(BookingRequest):
    operation_id: str = Field(min_length=1, max_length=100)


@app.post("/operations")
async def execute_operation(request: OperationRequest):
    booking = await create_booking(request)
    return {"operation_id": request.operation_id, **booking.model_dump()}


@app.get("/operations/{operation_id}")
async def lookup_operation(operation_id: str):
    booking = operations.get(operation_id)
    if booking is None:
        raise HTTPException(404, "No result visible for this operation.")
    return {"operation_id": operation_id, **booking.model_dump()}
