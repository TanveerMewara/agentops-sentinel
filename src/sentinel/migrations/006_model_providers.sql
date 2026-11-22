CREATE TABLE sentinel_model_provider_credentials (
    provider_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id),
    model_alias TEXT NOT NULL CHECK (model_alias ~ '^[a-z][a-z0-9_-]{2,63}$'),
    provider TEXT NOT NULL CHECK (provider IN ('openai')),
    model_id TEXT NOT NULL CHECK (length(trim(model_id)) BETWEEN 1 AND 100),
    encrypted_api_key BYTEA NOT NULL,
    key_hint TEXT NOT NULL CHECK (length(key_hint) BETWEEN 4 AND 12),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, model_alias)
);

CREATE TABLE sentinel_model_invocations (
    invocation_id UUID PRIMARY KEY,
    run_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    model_alias TEXT NOT NULL,
    provider TEXT NOT NULL,
    model_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('succeeded', 'fallback', 'failed')),
    provider_response_id TEXT,
    input_tokens INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    output_tokens INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    total_tokens INTEGER NOT NULL DEFAULT 0 CHECK (total_tokens >= 0),
    duration_ms INTEGER NOT NULL CHECK (duration_ms >= 0),
    error_class TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (run_id, organization_id)
        REFERENCES sentinel_runs(run_id, organization_id) ON DELETE CASCADE
);

CREATE TABLE sentinel_model_provider_events (
    event_id BIGSERIAL PRIMARY KEY,
    provider_id UUID NOT NULL REFERENCES sentinel_model_provider_credentials(provider_id),
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id),
    event_type TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    actor_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX sentinel_model_credentials_org_idx
    ON sentinel_model_provider_credentials (organization_id, model_alias);
CREATE INDEX sentinel_model_invocations_run_idx
    ON sentinel_model_invocations (run_id, created_at);
CREATE INDEX sentinel_model_provider_events_org_idx
    ON sentinel_model_provider_events (organization_id, event_id);
