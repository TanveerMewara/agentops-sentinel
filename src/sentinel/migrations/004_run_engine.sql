CREATE TABLE sentinel_agent_versions (
    agent_version_id UUID PRIMARY KEY,
    agent_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    version TEXT NOT NULL CHECK (version ~ '^[0-9]+\.[0-9]+\.[0-9]+$'),
    instructions TEXT NOT NULL CHECK (length(trim(instructions)) BETWEEN 1 AND 20000),
    model_alias TEXT NOT NULL CHECK (model_alias ~ '^[a-z][a-z0-9_-]{2,63}$'),
    max_steps INTEGER NOT NULL CHECK (max_steps BETWEEN 1 AND 100),
    created_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (agent_id, version),
    UNIQUE (agent_version_id, organization_id),
    FOREIGN KEY (agent_id, organization_id)
        REFERENCES sentinel_agents(agent_id, organization_id) ON DELETE CASCADE
);

CREATE TABLE sentinel_runs (
    run_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id),
    agent_id UUID NOT NULL,
    agent_version_id UUID NOT NULL,
    idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 8 AND 200),
    input_payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled', 'needs_review')),
    max_steps INTEGER NOT NULL CHECK (max_steps BETWEEN 1 AND 100),
    steps_used INTEGER NOT NULL DEFAULT 0 CHECK (steps_used >= 0 AND steps_used <= max_steps),
    created_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, idempotency_key),
    UNIQUE (run_id, organization_id),
    FOREIGN KEY (agent_id, organization_id)
        REFERENCES sentinel_agents(agent_id, organization_id),
    FOREIGN KEY (agent_version_id, organization_id)
        REFERENCES sentinel_agent_versions(agent_version_id, organization_id)
);

CREATE TABLE sentinel_run_tool_permissions (
    run_id UUID NOT NULL,
    tool_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    contract_snapshot JSONB NOT NULL,
    max_calls INTEGER NOT NULL CHECK (max_calls BETWEEN 1 AND 100),
    calls_used INTEGER NOT NULL DEFAULT 0 CHECK (calls_used >= 0 AND calls_used <= max_calls),
    PRIMARY KEY (run_id, tool_id),
    UNIQUE (run_id, tool_id, organization_id),
    FOREIGN KEY (run_id, organization_id)
        REFERENCES sentinel_runs(run_id, organization_id) ON DELETE CASCADE,
    FOREIGN KEY (tool_id, organization_id)
        REFERENCES sentinel_tools(tool_id, organization_id)
);

CREATE TABLE sentinel_tool_calls (
    tool_call_id UUID PRIMARY KEY,
    run_id UUID NOT NULL,
    tool_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 8 AND 200),
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    arguments JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'reserved'
        CHECK (status IN ('reserved', 'completed', 'failed', 'cancelled')),
    result JSONB,
    error TEXT CHECK (error IS NULL OR length(error) BETWEEN 1 AND 1000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    UNIQUE (run_id, idempotency_key),
    UNIQUE (run_id, sequence),
    FOREIGN KEY (run_id, tool_id, organization_id)
        REFERENCES sentinel_run_tool_permissions(run_id, tool_id, organization_id) ON DELETE CASCADE
);

CREATE TABLE sentinel_run_events (
    event_id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    event_type TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    actor_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (run_id, organization_id)
        REFERENCES sentinel_runs(run_id, organization_id) ON DELETE CASCADE
);

CREATE INDEX sentinel_agent_versions_agent_idx
    ON sentinel_agent_versions (organization_id, agent_id, created_at);
CREATE INDEX sentinel_runs_org_status_idx
    ON sentinel_runs (organization_id, status, created_at);
CREATE INDEX sentinel_tool_calls_run_idx ON sentinel_tool_calls (run_id, sequence);
CREATE INDEX sentinel_run_events_run_idx ON sentinel_run_events (run_id, event_id);
