"""Lesson 3: fictional booking service backed by PostgreSQL."""
import os
import time
from contextlib import asynccontextmanager
from uuid import uuid4

import psycopg
from fastapi import FastAPI, HTTPException
from psycopg.rows import dict_row
from pydantic import BaseModel, Field, model_validator
from lessons.booking_api import Booking, BookingRequest


class OperationRequest(BookingRequest):
    operation_id: str = Field(min_length=1, max_length=100)
    property_id: str | None = Field(default=None, min_length=1, max_length=100)
    property_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def property_pair(self):
        if (self.property_id is None) != (self.property_version is None):
            raise ValueError("Property ID and version must be supplied together.")
        return self


class OperationReceipt(BaseModel):
    operation_id: str
    booking_id: str
    customer: str
    slot: str
    property_id: str | None = None
    property_version: int | None = None

# Public local lesson credentials only, not deployment credentials.
DATABASE_URL = os.environ.get(
    "SENTINEL_LESSON_DATABASE_URL",
    "postgresql://sentinel_lesson:local_lesson_only@127.0.0.1:55432/sentinel_lesson",
)


def connect():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=5)


def initialize_database():
    with connect() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS lesson_bookings (
                booking_id TEXT PRIMARY KEY,
                operation_id TEXT UNIQUE,
                customer TEXT NOT NULL,
                slot TEXT NOT NULL
            )
        """)
        connection.execute("ALTER TABLE lesson_bookings ADD COLUMN IF NOT EXISTS property_id TEXT")
        connection.execute("ALTER TABLE lesson_bookings ADD COLUMN IF NOT EXISTS property_version INTEGER")


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="Sentinel Lesson 3: Persistent Bookings", lifespan=lifespan)


@app.get("/health")
def health():
    with connect() as connection:
        connection.execute("SELECT 1")
    return {"status": "ok"}


@app.get("/bookings", response_model=list[Booking])
def list_bookings():
    with connect() as connection:
        return connection.execute(
            "SELECT booking_id, customer, slot FROM lesson_bookings ORDER BY booking_id"
        ).fetchall()


@app.post("/bookings", response_model=Booking)
def create_booking(request: BookingRequest):
    # One row holds both the intended action ID and its result.
    with connect() as connection:
        booking = connection.execute(
            """INSERT INTO lesson_bookings (booking_id, operation_id, customer, slot, property_id, property_version)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (operation_id) DO NOTHING
               RETURNING booking_id, customer, slot, property_id, property_version""",
            (str(uuid4()), request.operation_id, request.customer, request.slot,
             getattr(request, "property_id", None), getattr(request, "property_version", None)),
        ).fetchone()
        created = booking is not None
        if not created:
            # Separate statement: fresh READ COMMITTED snapshot sees the winner
            # after a concurrent insert commits. This lesson has no delete API.
            booking = connection.execute(
                "SELECT booking_id, customer, slot, property_id, property_version FROM lesson_bookings WHERE operation_id = %s",
                (request.operation_id,),
            ).fetchone()
            if booking is None:
                raise HTTPException(503, "Result unavailable; reconciliation required.")
            if (booking["customer"], booking["slot"]) != (request.customer, request.slot):
                raise HTTPException(409, "Operation ID already used with different details.")
            if (booking["property_id"], booking["property_version"]) != (
                    getattr(request, "property_id", None), getattr(request, "property_version", None)):
                raise HTTPException(409, "Operation ID already used for another property version.")
    # Successful context exit commits before the intentionally delayed response.
    # FastAPI runs a normal def endpoint in a thread pool.
    if created:
        time.sleep(request.response_delay_seconds)
    return booking


@app.post("/operations", response_model=OperationReceipt)
def execute_operation(request: OperationRequest):
    booking = create_booking(request)
    return {"operation_id": request.operation_id, **booking}


@app.get("/operations/{operation_id}", response_model=OperationReceipt)
def lookup_operation(operation_id: str):
    with connect() as connection:
        booking = connection.execute(
            """SELECT operation_id, booking_id, customer, slot, property_id, property_version
               FROM lesson_bookings WHERE operation_id = %s""",
            (operation_id,),
        ).fetchone()
    if booking is None:
        raise HTTPException(404, "No result is visible for this operation.")
    return booking
