from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sentinel.adapters import AdapterContext
from sentinel.booking_adapter import EvidenceMismatch
from sentinel.calendar import NativeCalendar, SlotOffer, ReserveSlot, CalendarAdapter, RESERVE_CONTRACT, CANCEL_CONTRACT
from sentinel.schemas import ToolCreate


class CalendarTests(unittest.TestCase):
    def offer(self, **changes):
        start = datetime.now(timezone.utc) + timedelta(days=1)
        return {"property_id": str(uuid4()), "property_version": 1,
                "starts_at": start.isoformat(), "ends_at": (start + timedelta(minutes=30)).isoformat(), **changes}

    def test_naive_times_and_invalid_durations_are_rejected(self):
        for changes in ({"property_version": True}, {"starts_at": "2030-01-01T10:00:00"},
                        {"starts_at": "2030-01-01T10:00:00Z", "ends_at": "2030-01-01T10:04:00Z"},
                        {"starts_at": "2030-01-01T10:00:00Z", "ends_at": "2030-01-01T14:01:00Z"},
                        {"starts_at": "2030-01-01T10:00:00Z", "ends_at": "2030-01-01T09:30:00Z"}):
            with self.assertRaises(ValidationError):
                SlotOffer.model_validate(self.offer(**changes))

    def test_offset_times_are_normalized_to_utc(self):
        offer = SlotOffer.model_validate(self.offer(starts_at="2030-01-01T15:30:00+05:30", ends_at="2030-01-01T16:00:00+05:30"))
        self.assertEqual(offer.starts_at.hour, 10)
        self.assertEqual(offer.starts_at.utcoffset(), timedelta(0))

    def test_contracts_require_exact_approval_and_slot_details(self):
        for contract in (RESERVE_CONTRACT, CANCEL_CONTRACT):
            validated = ToolCreate.model_validate(contract)
            self.assertEqual(validated.approval_mode, "always")
            self.assertEqual(validated.risk_level, "high")
        with self.assertRaises(ValidationError):
            ReserveSlot.model_validate({"slot_id": str(uuid4())})

    def test_unauthorized_calendar_access_never_opens_database(self):
        database = MagicMock()
        calendar = NativeCalendar(database)
        for action in (lambda: calendar.offer(SimpleNamespace(role="reviewer"), None),
                       lambda: calendar.slots(SimpleNamespace(role="worker")),
                       lambda: calendar.reservations(SimpleNamespace(role="worker")),
                       lambda: calendar.withdraw(SimpleNamespace(role="reviewer"), uuid4())):
            with self.assertRaises(HTTPException) as caught:
                action()
            self.assertEqual(caught.exception.status_code, 403)
        database.connect.assert_not_called()

    def test_reconciliation_only_reads_and_missing_evidence_requires_review(self):
        database = MagicMock()
        connection = database.connect.return_value.__enter__.return_value
        connection.execute.return_value.fetchone.return_value = None
        context = AdapterContext(str(uuid4()), str(uuid4()), str(uuid4()), {"reservation_id": str(uuid4())}, CANCEL_CONTRACT)
        with self.assertRaises(EvidenceMismatch):
            CalendarAdapter(NativeCalendar(database), "cancel").reconcile(context)
        statements = [call.args[0].upper() for call in connection.execute.call_args_list]
        self.assertEqual(len(statements), 2)
        self.assertTrue(statements[0].startswith("SET TRANSACTION READ ONLY"))
        self.assertTrue(statements[1].startswith("SELECT "))
