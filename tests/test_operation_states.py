"""Run: python -m unittest discover -s tests -p test_operation_states.py -v"""
import importlib.util
from pathlib import Path
import sys
import unittest

path = Path(__file__).resolve().parents[1] / "lessons/04_operation_states.py"
spec = importlib.util.spec_from_file_location("operation_states_lesson", path)
model = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = model
spec.loader.exec_module(model)
Operation, State, Event, advance = model.Operation, model.State, model.Event, model.advance


class OperationStateTests(unittest.TestCase):
    def executing(self):
        return advance(Operation("test-operation"), Event.START)

    def test_timeout_is_unknown_and_preserves_previous_record(self):
        original = self.executing()
        updated = advance(original, Event.TIMEOUT)
        self.assertEqual(updated.state, State.UNKNOWN)
        self.assertEqual(original.state, State.EXECUTING)
        self.assertEqual(updated.operation_id, original.operation_id)

    def test_unknown_cannot_be_blindly_retried_or_declared_failed(self):
        unknown = advance(self.executing(), Event.TIMEOUT)
        for event in (Event.START, Event.REJECTED_WITHOUT_EFFECT):
            with self.subTest(event=event), self.assertRaises(ValueError):
                advance(unknown, event)

    def test_confirmation_records_result_and_history(self):
        unknown = advance(self.executing(), Event.TIMEOUT)
        result = advance(unknown, Event.CONFIRMED_SUCCESS, booking_id="booking-1")
        self.assertEqual(result.state, State.SUCCEEDED)
        self.assertEqual(result.booking_id, "booking-1")
        self.assertEqual(len(result.history), 3)

    def test_success_requires_result_and_other_events_cannot_attach_one(self):
        for value in (None, "", "   "):
            with self.subTest(value=value), self.assertRaises(ValueError):
                advance(self.executing(), Event.CONFIRMED_SUCCESS, booking_id=value)
        with self.assertRaises(ValueError):
            advance(self.executing(), Event.TIMEOUT, booking_id="booking-1")

    def test_unverifiable_outcome_requires_review(self):
        unknown = advance(self.executing(), Event.TIMEOUT)
        review = advance(unknown, Event.CANNOT_VERIFY)
        self.assertEqual(review.state, State.NEEDS_REVIEW)
        self.assertIsNone(review.booking_id)
        with self.assertRaises(ValueError):
            advance(review, Event.START)

    def test_terminal_states_reject_further_automatic_events(self):
        success = advance(self.executing(), Event.CONFIRMED_SUCCESS, booking_id="booking-1")
        failed = advance(self.executing(), Event.REJECTED_WITHOUT_EFFECT)
        self.assertEqual(failed.state, State.FAILED)
        for operation in (success, failed):
            for event in Event:
                with self.subTest(state=operation.state, event=event), self.assertRaises(ValueError):
                    advance(operation, event)


if __name__ == "__main__":
    unittest.main()
