from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sentinel.calendar import RESERVE_CONTRACT, NativeCalendar
from sentinel.calendar_workflow import configure, is_native_reservation, offered_slot, validate_native_decision
from sentinel.model_gateway import DeterministicEstateFlowProvider, ModelDecision, ModelRequest
from sentinel.schemas import LeadRunCreate


class CalendarWorkflowTests(unittest.TestCase):
    def test_direct_adapter_rechecks_frozen_lead_and_consent(self):
        context = SimpleNamespace(organization_id="tenant", run_id="run")
        lead_id = str(uuid4())
        for changes in ({}, {"current_version": 2}, {"qualification_status": "human_review"},
                        {"outreach_consent": False}):
            connection = MagicMock()
            lead = {"current_version": 1, "qualification_status": "qualified", "outreach_consent": True, **changes}
            connection.execute.return_value.fetchone.side_effect = [
                {"input_payload": {"lead_id": lead_id, "lead_version": 1}}, lead]
            self.assertEqual(NativeCalendar.lead_ready(connection, context), not changes)
            self.assertIn("FOR SHARE", connection.execute.call_args.args[0])
            self.assertEqual(connection.execute.call_args.args[1][0], "tenant")

    def test_missing_or_forged_lead_binding_never_reserves(self):
        context = SimpleNamespace(organization_id="tenant", run_id="run")
        for fields in ({"lead_id": str(uuid4())}, {"lead_id": str(uuid4()), "lead_version": True},
                       {"lead_id": str(uuid4()), "lead_version": 1.0},
                       {"lead_id": "invalid", "lead_version": 1}):
            connection = MagicMock()
            connection.execute.return_value.fetchone.return_value = {"input_payload": fields}
            self.assertFalse(NativeCalendar.lead_ready(connection, context))
            self.assertEqual(connection.execute.call_count, 1)

    def test_manual_unlinked_actions_keep_their_original_boundary(self):
        connection = MagicMock()
        connection.execute.return_value.fetchone.return_value = {"input_payload": {"calendar_action": "reserve"}}
        self.assertTrue(NativeCalendar.lead_ready(connection, SimpleNamespace(organization_id="tenant", run_id="run")))

    def fixture(self):
        start = datetime.now(timezone.utc) + timedelta(days=2)
        slot = {"slot_id": uuid4(), "property_id": uuid4(), "property_version": 2,
                "starts_at": start, "ends_at": start + timedelta(minutes=30), "available": True}
        return slot, [{"property": {"property_id": str(slot["property_id"]), "current_version": 2}}]

    def test_lead_launch_requires_one_explicit_scheduling_path(self):
        base = {"idempotency_key": "fixture-123", "agent_version_id": str(uuid4())}
        for fields in ({}, {"slot": "time", "native_slot_id": str(uuid4())}):
            with self.assertRaises(ValidationError):
                LeadRunCreate.model_validate({**base, **fields})
        self.assertIsNone(LeadRunCreate.model_validate({**base, "slot": "time"}).native_slot_id)
        self.assertIsNone(LeadRunCreate.model_validate({**base, "native_slot_id": str(uuid4())}).slot)

    def test_native_matching_includes_approval_and_frozen_schema(self):
        self.assertTrue(is_native_reservation({**RESERVE_CONTRACT, "tool_id": str(uuid4())}))
        for fields in ({"approval_mode": "never"}, {"version": "2.0.0"},
                       {"risk_level": "low"}, {"input_schema": {"type": "object"}}):
            self.assertFalse(is_native_reservation({**RESERVE_CONTRACT, **fields}))

    def test_native_provider_does_not_fall_back_to_legacy_booking(self):
        request = ModelRequest("", {"native_slot_id": str(uuid4()), "customer": "Buyer", "slot": "time",
                                    "calendar_slot": {}}, ({**RESERVE_CONTRACT, "tool_id": "native"},))
        changed = deepcopy(RESERVE_CONTRACT)
        changed["approval_mode"] = "never"
        with self.assertRaises(HTTPException):
            DeterministicEstateFlowProvider().decide(ModelRequest("", request.input_payload,
                ({**changed, "tool_id": "changed"},)))
        with self.assertRaises(HTTPException):
            DeterministicEstateFlowProvider().decide(ModelRequest("", request.input_payload, ()))

    def test_model_cannot_change_exact_resource_or_tool(self):
        arguments = {"slot_id": str(uuid4()), "property_id": str(uuid4()), "property_version": 2,
                     "starts_at": "2030-01-01T10:00:00Z", "ends_at": "2030-01-01T10:30:00Z"}
        tool = {**RESERVE_CONTRACT, "tool_id": "native"}
        validate_native_decision(ModelDecision("native", arguments, ""), tool, arguments)
        for fields in ({"slot_id": str(uuid4())}, {"property_version": 3}, {"property_version": 2.0},
                       {"ends_at": "2030-01-01T11:00:00Z"}):
            with self.assertRaises(HTTPException):
                validate_native_decision(ModelDecision("native", {**arguments, **fields}, ""), tool, arguments)
        with self.assertRaises(HTTPException):
            validate_native_decision(ModelDecision("other", arguments, ""), tool, arguments)

    def test_slot_lookup_is_tenant_bound_and_preserves_current_availability(self):
        slot, recommendations = self.fixture()
        database = MagicMock()
        connection = database.connect.return_value.__enter__.return_value
        connection.execute.return_value.fetchone.return_value = slot
        principal = SimpleNamespace(organization_id="tenant-a")
        arguments, available = offered_slot(database, principal, str(slot["slot_id"]), recommendations)
        self.assertTrue(available)
        self.assertEqual(arguments["property_id"], str(slot["property_id"]))
        self.assertEqual(connection.execute.call_args.args[1], ("tenant-a", str(slot["slot_id"])))
        slot["available"] = False
        self.assertFalse(offered_slot(database, principal, str(slot["slot_id"]), recommendations)[1])
        # A stale listing version cannot appear in a current retrieval snapshot;
        # terminate its unavailable offer rather than repeatedly retry planning.
        self.assertFalse(offered_slot(database, principal, str(slot["slot_id"]), [])[1])

    def test_unknown_or_unrecommended_slot_cannot_be_proposed(self):
        slot, _ = self.fixture()
        database = MagicMock()
        connection = database.connect.return_value.__enter__.return_value
        connection.execute.return_value.fetchone.return_value = slot
        with self.assertRaises(HTTPException) as caught:
            offered_slot(database, SimpleNamespace(organization_id="tenant"), str(slot["slot_id"]), [])
        self.assertEqual(caught.exception.status_code, 409)
        connection.execute.return_value.fetchone.return_value = None
        with self.assertRaises(HTTPException) as caught:
            offered_slot(database, SimpleNamespace(organization_id="tenant"), str(slot["slot_id"]), [])
        self.assertEqual(caught.exception.status_code, 404)

    def test_configuration_denies_reviewers_and_workers_before_writes(self):
        database, adapters = MagicMock(), MagicMock()
        for role in ("reviewer", "worker"):
            with self.assertRaises(HTTPException):
                configure(database, SimpleNamespace(role=role), adapters)
        database.connect.assert_not_called()
        adapters.resolve.assert_not_called()

    def test_native_provider_uses_an_independent_argument_copy(self):
        slot = {"slot_id": str(uuid4())}
        decision = DeterministicEstateFlowProvider().decide(ModelRequest("",
            {"native_slot_id": slot["slot_id"], "calendar_slot": slot},
            ({**RESERVE_CONTRACT, "tool_id": "native"},)))
        decision.arguments["slot_id"] = "changed"
        self.assertNotEqual(slot["slot_id"], "changed")
