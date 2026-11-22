import unittest
from uuid import uuid4

from fastapi import HTTPException

from sentinel.booking_adapter import BookingAdapter, EvidenceMismatch
from sentinel.model_gateway import DeterministicEstateFlowProvider, ModelRequest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sentinel.config import Settings
from sentinel.main import create_app


class PropertyBookingTests(unittest.TestCase):
    def test_browser_can_preflight_draft_edit_without_database_access(self):
        app = create_app(Settings(database_url="postgresql://unused@127.0.0.1/unused",
            auth_pepper="test-only-pepper", booking_service_url="http://127.0.0.1:1",
            credential_encryption_key=Fernet.generate_key().decode()))
        response = TestClient(app).options("/v1/followups/" + str(uuid4()), headers={
            "Origin": "http://localhost:3000", "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "content-type,x-api-key"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("PATCH", response.headers["access-control-allow-methods"])

    def test_receipt_must_prove_exact_property_and_version(self):
        action = {"customer": "Fictional Buyer", "slot": "2030-01-01T10:00:00Z",
                  "property_id": str(uuid4()), "property_version": 3}
        receipt = {"operation_id": "op-1", "booking_id": "booking-1", **action}
        self.assertEqual(BookingAdapter.validate("op-1", action, receipt), "booking-1")
        for replacement in ({"property_id": str(uuid4())}, {"property_version": 2},
                            {"property_id": None, "property_version": None}):
            with self.assertRaises(EvidenceMismatch):
                BookingAdapter.validate("op-1", action, {**receipt, **replacement})

    def test_provider_prefers_property_contract_and_requires_evidence(self):
        legacy = {"tool_id": "legacy", "name": "book_viewing", "input_schema": {"properties": {}}}
        bound = {"tool_id": "bound", "name": "book_viewing",
                 "input_schema": {"properties": {"property_id": {}, "property_version": {}}}}
        payload = {"customer": "Buyer", "slot": "2030-01-01T10:00:00Z"}
        provider = DeterministicEstateFlowProvider()
        with self.assertRaises(HTTPException):
            provider.decide(ModelRequest("", payload, (legacy, bound)))
        property_id = str(uuid4())
        payload["property_recommendations"] = [{"property": {
            "property_id": property_id, "current_version": 4}}]
        decision = provider.decide(ModelRequest("", payload, (legacy, bound)))
        self.assertEqual(decision.tool_id, "bound")
        self.assertEqual(decision.arguments["property_id"], property_id)
        self.assertEqual(decision.arguments["property_version"], 4)
