ALTER TABLE sentinel_tool_calls
    DROP CONSTRAINT sentinel_tool_calls_status_check;

ALTER TABLE sentinel_tool_calls
    ADD COLUMN requires_approval BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN action_hash TEXT,
    ADD COLUMN current_attempt_id UUID,
    ADD COLUMN lease_expires_at TIMESTAMPTZ,
    ADD COLUMN external_id TEXT,
    ADD CONSTRAINT sentinel_tool_calls_status_check CHECK (status IN (
        'reserved', 'awaiting_approval', 'authorized', 'executing', 'unknown',
        'completed', 'failed', 'cancelled', 'needs_review'
    )),
    ADD CONSTRAINT sentinel_tool_calls_identity_org_unique
        UNIQUE (tool_call_id, organization_id);

CREATE TABLE sentinel_tool_call_approvals (
    approval_id UUID PRIMARY KEY,
    tool_call_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    action_hash TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('approved', 'consumed', 'revoked')),
    approved_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    approved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    FOREIGN KEY (tool_call_id, organization_id)
        REFERENCES sentinel_tool_calls(tool_call_id, organization_id) ON DELETE CASCADE
);

CREATE INDEX sentinel_tool_call_approvals_call_idx
    ON sentinel_tool_call_approvals (tool_call_id, approved_at DESC);
CREATE INDEX sentinel_tool_calls_execution_idx
    ON sentinel_tool_calls (organization_id, status, lease_expires_at);
