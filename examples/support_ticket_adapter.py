"""Durable local sandbox adapter; this is not an external CRM integration."""
from contextlib import closing
import hashlib
import json
import sqlite3

from sentinel.adapters import AdapterResult
from sentinel.booking_adapter import EvidenceMismatch, UncertainOutcome

INPUT_SCHEMA = {"type": "object", "properties": {
    "queue": {"type": "string", "enum": ["billing", "technical"]},
    "priority": {"type": "string", "enum": ["standard", "urgent"]}},
    "required": ["queue", "priority"], "additionalProperties": False}
OUTPUT_SCHEMA = {"type": "object", "properties": {
    **INPUT_SCHEMA["properties"], "ticket_id": {"type": "string", "minLength": 1}},
    "required": ["ticket_id", "queue", "priority"], "additionalProperties": False}
CONTRACT = {"name": "create_support_ticket", "version": "1.0.0",
    "description": "Create a synthetic support ticket in a durable local sandbox.",
    "input_schema": INPUT_SCHEMA, "output_schema": OUTPUT_SCHEMA,
    "risk_level": "medium", "approval_mode": "always"}


class SupportTicketAdapter:
    def __init__(self, path, *, lose_reply=False):
        self.path = str(path)
        self.lose_reply = lose_reply
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS receipts (
                tool_call_id TEXT PRIMARY KEY, organization_id TEXT NOT NULL,
                arguments_hash TEXT NOT NULL, result TEXT NOT NULL)""")
            connection.commit()

    @staticmethod
    def fingerprint(context):
        return hashlib.sha256(json.dumps(context.arguments, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def execute(self, context):
        result = {"ticket_id": "ticket_" + context.tool_call_id, **context.arguments}
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("INSERT INTO receipts VALUES (?,?,?,?) ON CONFLICT(tool_call_id) DO NOTHING",
                (context.tool_call_id, context.organization_id, self.fingerprint(context), json.dumps(result)))
            connection.commit()
        outcome = self.reconcile(context)
        if self.lose_reply:
            raise UncertainOutcome("Synthetic reply lost after commit.")
        return outcome

    def reconcile(self, context):
        with closing(sqlite3.connect(self.path, timeout=10)) as connection:
            row = connection.execute("SELECT organization_id, arguments_hash, result FROM receipts WHERE tool_call_id=?",
                                     (context.tool_call_id,)).fetchone()
        if row is None:
            raise UncertainOutcome("No durable evidence exists.")
        if row[0] != context.organization_id or row[1] != self.fingerprint(context):
            raise EvidenceMismatch("Stored receipt does not match the authorized request.")
        result = json.loads(row[2])
        return AdapterResult(result["ticket_id"], result)
