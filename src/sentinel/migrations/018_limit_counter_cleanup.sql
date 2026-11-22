-- Counters are operational state, not the append-only access audit. Removing a
-- fixture/retired key must not leave orphan counters or prevent key cleanup.
ALTER TABLE sentinel_request_limits DROP CONSTRAINT sentinel_request_limits_api_key_id_fkey;
ALTER TABLE sentinel_request_limits ADD CONSTRAINT sentinel_request_limits_api_key_id_fkey
    FOREIGN KEY (api_key_id) REFERENCES sentinel_api_keys(api_key_id) ON DELETE CASCADE;
