import unittest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, field_validator
from sentinel.http_security import ResponseSecurity, validation_error_response


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str

    @field_validator("value")
    @classmethod
    def reject(cls, value):
        raise ValueError("Rejected private value: " + value)


class HttpSecurityTests(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.add_middleware(ResponseSecurity)
        app.add_exception_handler(RequestValidationError, validation_error_response)

        @app.post("/v1/probe")
        def probe(body: Payload):
            return {}

        self.http = TestClient(app)

    def test_validation_does_not_echo_values_messages_or_extra_keys(self):
        marker = "snt_private_contact_data"
        response = self.http.post("/v1/probe", json={"value": marker, marker: marker})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(marker, response.text)
        self.assertNotIn("Rejected", response.text)
        self.assertEqual(len(response.json()["detail"]), 2)
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_malformed_json_and_missing_routes_have_protected_responses(self):
        response = self.http.post("/v1/probe", content='{"snt_private":', headers={"Content-Type": "application/json"})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("snt_private", response.text)
        for response in (response, self.http.get("/v1/missing")):
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(response.headers["x-content-type-options"], "nosniff")
            self.assertEqual(response.headers["referrer-policy"], "no-referrer")
            self.assertEqual(response.headers["x-frame-options"], "DENY")
