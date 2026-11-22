CREATE TABLE sentinel_external_traces (
    trace_id UUID PRIMARY KEY,
    run_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 8 AND 200),
    evidence JSONB NOT NULL CHECK (jsonb_typeof(evidence) = 'object'),
    content_hash TEXT NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    created_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, organization_id),
    FOREIGN KEY (run_id, organization_id)
        REFERENCES sentinel_runs(run_id, organization_id) ON DELETE CASCADE
);
