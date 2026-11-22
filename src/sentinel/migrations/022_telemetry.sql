CREATE TABLE sentinel_telemetry_policies (
    organization_id UUID PRIMARY KEY REFERENCES sentinel_organizations(organization_id) ON DELETE CASCADE,
    retention_days INTEGER NOT NULL DEFAULT 30 CHECK (retention_days BETWEEN 1 AND 365),
    required_signals TEXT[] NOT NULL DEFAULT ARRAY['traces']::TEXT[],
    require_token_usage BOOLEAN NOT NULL DEFAULT FALSE,
    require_cost BOOLEAN NOT NULL DEFAULT FALSE,
    updated_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (required_signals <@ ARRAY['traces','metrics','logs']::TEXT[])
);

CREATE TABLE sentinel_telemetry_rate_cards (
    rate_card_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id) ON DELETE CASCADE,
    pricing_key TEXT NOT NULL CHECK (pricing_key ~ '^[a-z][a-z0-9_.-]{2,63}$'),
    version INTEGER NOT NULL CHECK (version > 0),
    input_usd_per_million NUMERIC(18,8) NOT NULL CHECK (input_usd_per_million >= 0),
    output_usd_per_million NUMERIC(18,8) NOT NULL CHECK (output_usd_per_million >= 0),
    created_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, pricing_key, version)
);

CREATE TABLE sentinel_telemetry_batches (
    telemetry_batch_id UUID PRIMARY KEY,
    run_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    signal_type TEXT NOT NULL CHECK (signal_type IN ('metrics','logs')),
    content_hash TEXT NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    summary JSONB NOT NULL CHECK (jsonb_typeof(summary) = 'object'),
    received_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    UNIQUE (run_id, organization_id, signal_type, content_hash),
    FOREIGN KEY (run_id, organization_id)
        REFERENCES sentinel_runs(run_id, organization_id) ON DELETE CASCADE
);

CREATE INDEX sentinel_telemetry_batches_expiry
    ON sentinel_telemetry_batches (organization_id, expires_at);

ALTER TABLE sentinel_pending_otlp_traces
    ADD COLUMN expires_at TIMESTAMPTZ NOT NULL DEFAULT (now() + interval '30 days');

CREATE INDEX sentinel_pending_otlp_traces_expiry
    ON sentinel_pending_otlp_traces (organization_id, expires_at);
