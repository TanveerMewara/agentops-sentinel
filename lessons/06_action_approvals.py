"""Lesson 6: exact-action approval rules. In memory; no real authentication yet."""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from uuid import uuid4


@dataclass(frozen=True)
class BookingAction:
    operation_id: str
    customer: str
    slot: str


class ApprovalState(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"
    CONSUMED = "consumed"


@dataclass(frozen=True)
class Approval:
    approval_id: str
    action: BookingAction
    state: ApprovalState = ApprovalState.PENDING
    expires_at: datetime | None = None


class ApprovalBook:
    """A single-process learning model, not a secure approval service."""
    def __init__(self):
        self._records: dict[str, Approval] = {}

    def propose(self, action: BookingAction) -> Approval:
        if any(not isinstance(value, str) or not value.strip()
               for value in (action.operation_id, action.customer, action.slot)):
            raise ValueError("Action fields must contain text.")
        approval = Approval(uuid4().hex, action)
        self._records[approval.approval_id] = approval
        return approval

    def get(self, approval_id: str) -> Approval:
        if approval_id not in self._records:
            raise ValueError("Unknown approval ID.")
        return self._records[approval_id]

    @staticmethod
    def check_time(now: datetime):
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("Use a timezone-aware time.")

    def approve(self, approval_id: str, *, now: datetime,
                valid_for: timedelta = timedelta(minutes=5)) -> Approval:
        self.check_time(now)
        approval = self.get(approval_id)
        if approval.state != ApprovalState.PENDING:
            raise ValueError("Only a pending proposal can be approved.")
        if valid_for <= timedelta(0):
            raise ValueError("Approval duration must be positive.")
        approved = replace(approval, state=ApprovalState.APPROVED, expires_at=now + valid_for)
        self._records[approval_id] = approved
        return approved

    def reject(self, approval_id: str) -> Approval:
        approval = self.get(approval_id)
        if approval.state != ApprovalState.PENDING:
            raise ValueError("Only a pending proposal can be rejected.")
        rejected = replace(approval, state=ApprovalState.REJECTED)
        self._records[approval_id] = rejected
        return rejected

    def revoke(self, approval_id: str) -> Approval:
        approval = self.get(approval_id)
        if approval.state != ApprovalState.APPROVED:
            raise ValueError("Only an unused approved proposal can be revoked.")
        revoked = replace(approval, state=ApprovalState.REVOKED)
        self._records[approval_id] = revoked
        return revoked

    def consume(self, approval_id: str, action: BookingAction, *, now: datetime) -> BookingAction:
        """Check permission for this exact action and mark the grant used locally."""
        self.check_time(now)
        approval = self.get(approval_id)
        if approval.state != ApprovalState.APPROVED:
            raise ValueError(f"Approval is {approval.state.value}, not usable.")
        if approval.expires_at is None or now >= approval.expires_at:
            raise ValueError("Approval has expired.")
        if approval.action != action:
            raise ValueError("Action changed; request a new approval.")
        self._records[approval_id] = replace(approval, state=ApprovalState.CONSUMED)
        return approval.action


def main():
    now = datetime.now(timezone.utc)
    book = ApprovalBook()
    action = BookingAction("viewing-001", "Asha", "2030-01-15 10:00")
    proposal = book.propose(action)
    book.approve(proposal.approval_id, now=now)
    print("Approved details:", action)
    try:
        book.consume(proposal.approval_id, replace(action, slot="2030-01-15 11:00"), now=now)
    except ValueError as error:
        print("Changed appointment blocked:", error)
    permitted = book.consume(proposal.approval_id, action, now=now)
    print("Original action passed the local approval check:", permitted)
    try:
        book.consume(proposal.approval_id, action, now=now)
    except ValueError as error:
        print("Reusing the same approval blocked:", error)
    print("No booking was submitted. This lesson checks approval rules only.")


if __name__ == "__main__":
    main()
