CREATE TABLE sentinel_request_limits (
    api_key_id UUID PRIMARY KEY REFERENCES sentinel_api_keys(api_key_id),
    window_started_at TIMESTAMPTZ NOT NULL,
    request_count INTEGER NOT NULL CHECK (request_count >= 0),
    blocked_count BIGINT NOT NULL DEFAULT 0 CHECK (blocked_count >= 0),
    last_blocked_at TIMESTAMPTZ
);
