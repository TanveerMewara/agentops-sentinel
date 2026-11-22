import importlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

lesson = importlib.import_module("lessons.06_action_approvals")


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.book = lesson.ApprovalBook()
        self.action = lesson.BookingAction("operation-1", "Asha", "2030-01-15 10:00")
        self.proposal = self.book.propose(self.action)

    def approve(self):
        return self.book.approve(self.proposal.approval_id, now=self.now)

    def test_unapproved_and_unknown_grants_are_rejected(self):
        for approval_id in (self.proposal.approval_id, "missing"):
            with self.subTest(approval_id=approval_id), self.assertRaises(ValueError):
                self.book.consume(approval_id, self.action, now=self.now)

    def test_all_action_fields_are_bound_and_mismatch_does_not_consume(self):
        self.approve()
        for field in ("operation_id", "customer", "slot"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.book.consume(self.proposal.approval_id, replace(self.action, **{field: "changed"}), now=self.now)
        result = self.book.consume(self.proposal.approval_id, self.action, now=self.now)
        self.assertEqual(result, self.action)

    def test_exact_expiry_boundary_is_rejected(self):
        approval = self.approve()
        with self.assertRaises(ValueError):
            self.book.consume(approval.approval_id, self.action, now=approval.expires_at)

    def test_just_before_expiry_is_allowed(self):
        approval = self.approve()
        self.assertEqual(self.book.consume(approval.approval_id, self.action,
                         now=approval.expires_at - timedelta(microseconds=1)), self.action)

    def test_revocation_and_rejection_block_execution(self):
        self.approve()
        self.book.revoke(self.proposal.approval_id)
        with self.assertRaises(ValueError):
            self.book.consume(self.proposal.approval_id, self.action, now=self.now)
        other = self.book.propose(self.action)
        self.book.reject(other.approval_id)
        with self.assertRaises(ValueError):
            self.book.approve(other.approval_id, now=self.now)

    def test_used_approval_cannot_be_consumed_or_approved_again(self):
        self.approve()
        self.book.consume(self.proposal.approval_id, self.action, now=self.now)
        with self.assertRaises(ValueError):
            self.book.consume(self.proposal.approval_id, self.action, now=self.now)
        with self.assertRaises(ValueError):
            self.book.approve(self.proposal.approval_id, now=self.now)

    def test_pending_snapshot_does_not_change_when_approved(self):
        self.approve()
        self.assertEqual(self.proposal.state, lesson.ApprovalState.PENDING)
        self.assertEqual(self.book.get(self.proposal.approval_id).state, lesson.ApprovalState.APPROVED)

    def test_invalid_duration_and_naive_clock_are_rejected(self):
        with self.assertRaises(ValueError):
            self.book.approve(self.proposal.approval_id, now=self.now, valid_for=timedelta(0))
        with self.assertRaises(ValueError):
            self.book.approve(self.proposal.approval_id, now=datetime(2030, 1, 1))


if __name__ == "__main__":
    unittest.main()
