CREATE TABLE sentinel_organizations (
    organization_id UUID PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sentinel_api_keys (
    api_key_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id),
    key_prefix TEXT NOT NULL UNIQUE,
    key_digest TEXT NOT NULL,
    label TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'reviewer', 'developer', 'worker')),
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sentinel_operations (
    operation_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id),
    idempotency_key TEXT NOT NULL,
    action_type TEXT NOT NULL,
    action_payload JSONB NOT NULL,
    action_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'awaiting_approval', 'authorized', 'executing', 'unknown',
        'succeeded', 'failed', 'needs_review', 'rejected'
    )),
    external_id TEXT,
    last_error TEXT,
    created_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, idempotency_key)
);

CREATE TABLE sentinel_approvals (
    approval_id UUID PRIMARY KEY,
    operation_id UUID NOT NULL REFERENCES sentinel_operations(operation_id),
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id),
    action_hash TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('approved', 'consumed', 'revoked')),
    approved_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    approved_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ
);

CREATE INDEX sentinel_approvals_operation_idx
    ON sentinel_approvals (operation_id, approved_at DESC);

CREATE TABLE sentinel_operation_events (
    event_id BIGSERIAL PRIMARY KEY,
    operation_id UUID NOT NULL REFERENCES sentinel_operations(operation_id),
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id),
    event_type TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    actor_key_id UUID REFERENCES sentinel_api_keys(api_key_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX sentinel_events_operation_idx
    ON sentinel_operation_events (operation_id, event_id);
