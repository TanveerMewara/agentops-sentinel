CREATE TABLE sentinel_pending_otlp_traces (
    pending_trace_id UUID PRIMARY KEY,
    run_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    selected_trace_id TEXT NOT NULL CHECK (selected_trace_id ~ '^[0-9a-f]{32}$'),
    evidence JSONB NOT NULL CHECK (jsonb_typeof(evidence) = 'object'),
    content_hash TEXT NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    received_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, organization_id),
    FOREIGN KEY (run_id, organization_id)
        REFERENCES sentinel_runs(run_id, organization_id) ON DELETE CASCADE
);
