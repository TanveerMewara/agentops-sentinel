from copy import deepcopy
import unittest
from sentinel.adapters import AdapterContext, AdapterRegistry, AdapterResult
from sentinel.booking_adapter import EvidenceMismatch, UncertainOutcome
from sentinel.security import Principal
from fastapi import HTTPException


CONTRACT = {"name": "test_adapter", "version": "1.0.0", "description": "Test adapter.",
    "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    "output_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    "risk_level": "medium", "approval_mode": "always"}


class Adapter:
    def execute(self, context):
        return AdapterResult("receipt", {})
    reconcile = execute


class AdapterTests(unittest.TestCase):
    def test_exact_contract_and_version_are_required(self):
        registry = AdapterRegistry()
        registry.install(CONTRACT, Adapter())
        self.assertTrue(registry.supports(CONTRACT))
        for changed in ({**CONTRACT, "version": "2.0.0"}, {**CONTRACT, "approval_mode": "never"},
                        {**CONTRACT, "output_schema": {**CONTRACT["output_schema"], "required": []}}):
            with self.assertRaises(HTTPException):
                registry.resolve(changed)

    def test_installation_rejects_overrides_and_incomplete_adapters(self):
        registry = AdapterRegistry()
        registry.install(CONTRACT, Adapter())
        with self.assertRaises(ValueError):
            registry.install(CONTRACT, Adapter())
        with self.assertRaises(ValueError):
            AdapterRegistry().install(CONTRACT, object())
        with self.assertRaises(ValueError):
            AdapterRegistry().install({**CONTRACT, "name": "book_viewing"}, Adapter())

    def test_adapter_mutation_cannot_change_frozen_call(self):
        class Mutating(Adapter):
            def execute(self, context):
                context.arguments["private"] = "changed"
                context.contract["version"] = "changed"
                return AdapterResult("receipt", {})
        registry = AdapterRegistry()
        registry.install(CONTRACT, Mutating())
        call = {"run_id": "run", "tool_call_id": "call", "arguments": {}, "contract_snapshot": deepcopy(CONTRACT)}
        registry.invoke("execute", call, Principal("key", "org", "worker"))
        self.assertEqual(call["arguments"], {})
        self.assertEqual(call["contract_snapshot"]["version"], "1.0.0")

    def test_unexpected_errors_become_sanitized_uncertain_outcomes(self):
        class Broken(Adapter):
            def execute(self, context):
                raise RuntimeError("snt_private_key customer-private")
        registry = AdapterRegistry()
        registry.install(CONTRACT, Broken())
        call = {"run_id": "run", "tool_call_id": "call", "arguments": {}, "contract_snapshot": CONTRACT}
        with self.assertRaises(UncertainOutcome) as caught:
            registry.invoke("execute", call, Principal("key", "org", "worker"))
        self.assertNotIn("private", str(caught.exception))

    def test_invalid_evidence_is_not_accepted(self):
        class Invalid(Adapter):
            def execute(self, context):
                return AdapterResult("", {})
        registry = AdapterRegistry()
        registry.install(CONTRACT, Invalid())
        call = {"run_id": "run", "tool_call_id": "call", "arguments": {}, "contract_snapshot": CONTRACT}
        with self.assertRaises(EvidenceMismatch):
            registry.invoke("execute", call, Principal("key", "org", "worker"))
