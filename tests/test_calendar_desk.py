from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sentinel.adapters import AdapterRegistry
from sentinel.calendar import RESERVE_CONTRACT
from sentinel.calendar_desk import CalendarProposal, configure, propose, queue, close


class CalendarDeskTests(unittest.TestCase):
    def test_cancel_proposal_is_strict_and_has_bounded_identity(self):
        good = {"action": "cancel", "idempotency_key": "calendar_test_01", "arguments": {"reservation_id": str(uuid4())}}
        self.assertEqual(CalendarProposal.model_validate(good).action, "cancel")
        for changes in ({"idempotency_key": "short"}, {"idempotency_key": "x" * 181},
                        {"idempotency_key": "bad space"}, {"action": "execute"},
                        {"arguments": {"reservation_id": str(uuid4()), "email": "private@example.test"}}, {"extra": True}):
            with self.assertRaises(ValidationError):
                CalendarProposal.model_validate({**good, **changes})

    def test_reservation_requires_complete_exact_arguments(self):
        with self.assertRaises(ValidationError):
            CalendarProposal.model_validate({"action": "reserve", "idempotency_key": "calendar_test_02", "arguments": {"slot_id": str(uuid4())}})

    def test_disallowed_proposal_and_setup_roles_never_open_database(self):
        database = MagicMock()
        for role in ("reviewer", "worker"):
            for operation in (configure, propose):
                with self.assertRaises(HTTPException) as caught:
                    operation(database, SimpleNamespace(role=role), AdapterRegistry(), *([None] if operation is propose else []))
                self.assertEqual(caught.exception.status_code, 403)
        database.connect.assert_not_called()

    def test_uninstalled_calendar_setup_has_no_registry_side_effect(self):
        database = MagicMock()
        with self.assertRaises(HTTPException) as caught:
            configure(database, SimpleNamespace(role="developer"), AdapterRegistry())
        self.assertEqual(caught.exception.status_code, 501)
        database.connect.assert_not_called()

    def test_unknown_queue_role_never_opens_database(self):
        database = MagicMock()
        with self.assertRaises(HTTPException) as caught:
            queue(database, SimpleNamespace(role="observer"), AdapterRegistry(), 10)
        self.assertEqual(caught.exception.status_code, 403)
        database.connect.assert_not_called()

    def test_reviewers_cannot_close_manual_runs(self):
        database = MagicMock()
        with self.assertRaises(HTTPException) as caught:
            close(database, SimpleNamespace(role="reviewer"), uuid4())
        self.assertEqual(caught.exception.status_code, 403)
        database.connect.assert_not_called()

    def test_unknown_action_cannot_be_closed_as_successful(self):
        database = MagicMock()
        database.connect.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = {
            "slug": "estateflow_calendar_desk", "max_steps": 1, "status": "unknown", "contract_snapshot": RESERVE_CONTRACT}
        with self.assertRaises(HTTPException) as caught:
            close(database, SimpleNamespace(role="worker", organization_id=str(uuid4())), uuid4())
        self.assertEqual(caught.exception.status_code, 409)
