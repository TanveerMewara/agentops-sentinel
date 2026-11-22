import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from sentinel.model_gateway import ModelGateway, ModelRequest, OpenAIResponsesProvider
from sentinel.provider_registry import CredentialCipher


class ModelGatewayTests(unittest.TestCase):
    def setUp(self):
        self.gateway = ModelGateway()
        self.tool = {
            "tool_id": "tool-1",
            "name": "book_viewing",
            "version": "1.0.0",
            "description": "Book one viewing.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "customer": {"type": "string"}, "slot": {"type": "string"},
                },
                "required": ["customer", "slot"],
                "additionalProperties": False,
            },
        }

    def test_deterministic_provider_returns_structured_tool_decision(self):
        decision = self.gateway.decide("deterministic_estateflow", ModelRequest(
            instructions="Arrange a viewing.",
            input_payload={"customer": " Asha ", "slot": " 2030-01-01T10:00:00Z "},
            available_tools=(self.tool,),
        ))
        self.assertEqual(decision.tool_id, "tool-1")
        self.assertEqual(decision.arguments, {
            "customer": "Asha", "slot": "2030-01-01T10:00:00Z",
        })

    def test_unknown_alias_is_rejected(self):
        with self.assertRaises(HTTPException) as raised:
            self.gateway.decide("unconfigured", ModelRequest("", {}, (self.tool,)))
        self.assertEqual(raised.exception.status_code, 409)

    def test_missing_required_input_is_rejected(self):
        with self.assertRaises(HTTPException) as raised:
            self.gateway.decide("deterministic_estateflow", ModelRequest(
                instructions="Arrange a viewing.",
                input_payload={"customer": "Asha"},
                available_tools=(self.tool,),
            ))
        self.assertEqual(raised.exception.status_code, 422)

    def test_openai_provider_requests_strict_non_stored_structured_output(self):
        captured = {}

        class Responses:
            def create(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(
                    id="resp_test",
                    output_text=(
                        '{"tool_id":"tool-1","arguments":{"customer":"Asha",'
                        '"slot":"2030-01-01"},"explanation":"Requested by user."}'
                    ),
                    usage=SimpleNamespace(input_tokens=20, output_tokens=10, total_tokens=30),
                )

        def client_factory(**kwargs):
            captured["client"] = kwargs
            return SimpleNamespace(responses=Responses())

        provider = OpenAIResponsesProvider("sk-test-secret", "configured-model", 7, client_factory)
        decision = provider.decide(ModelRequest(
            "Arrange a viewing.", {"customer": "Asha", "slot": "2030-01-01"},
            (self.tool,),
        ))
        self.assertEqual(decision.tool_id, "tool-1")
        self.assertEqual(captured["client"]["timeout"], 7)
        self.assertEqual(captured["client"]["max_retries"], 0)
        self.assertFalse(captured["store"])
        self.assertTrue(captured["text"]["format"]["strict"])
        self.assertEqual(provider.last_metadata["total_tokens"], 30)

    def test_credential_cipher_round_trip_does_not_leave_plaintext(self):
        cipher = CredentialCipher(
            "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="
        )
        ciphertext = cipher.encrypt("sk-a-secret-that-must-not-be-stored")
        self.assertNotIn(b"sk-a-secret", ciphertext)
        self.assertEqual(
            cipher.decrypt(ciphertext), "sk-a-secret-that-must-not-be-stored"
        )

    def test_hosted_timeout_uses_validated_fallback_and_records_it(self):
        statements = []

        class Connection:
            def execute(self, statement, parameters):
                statements.append((statement, parameters))

        class Database:
            @contextmanager
            def connect(self):
                yield Connection()

        class FailingResponses:
            def create(self, **kwargs):
                raise TimeoutError("hosted provider timed out")

        def client_factory(**kwargs):
            return SimpleNamespace(responses=FailingResponses())

        request = ModelRequest(
            "Arrange a viewing.", {"customer": "Asha", "slot": "2030-01-01"},
            (self.tool,), organization_id="00000000-0000-0000-0000-000000000001",
            run_id="00000000-0000-0000-0000-000000000002",
        )
        gateway = ModelGateway(
            database=Database(), cipher=object(), client_factory=client_factory
        )
        with patch("sentinel.model_gateway.get_model_credential", return_value={
            "api_key": "sk-test", "model_id": "configured-model",
        }):
            decision = gateway.decide("openai_primary", request)
        self.assertTrue(decision.explanation.startswith("Deterministic fallback:"))
        invocation_parameters = statements[-1][1]
        self.assertEqual(invocation_parameters[6], "fallback")
        self.assertEqual(invocation_parameters[12], "TimeoutError")


if __name__ == "__main__":
    unittest.main()
