ALTER TABLE sentinel_operations
    ADD COLUMN current_attempt_id UUID,
    ADD COLUMN lease_expires_at TIMESTAMPTZ;

CREATE INDEX sentinel_operations_recovery_idx
    ON sentinel_operations (status, lease_expires_at)
    WHERE status = 'executing';
