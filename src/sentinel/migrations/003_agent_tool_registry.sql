CREATE TABLE sentinel_agents (
    agent_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id),
    slug TEXT NOT NULL CHECK (slug ~ '^[a-z][a-z0-9_]{2,63}$'),
    display_name TEXT NOT NULL CHECK (length(trim(display_name)) BETWEEN 1 AND 100),
    description TEXT NOT NULL DEFAULT '' CHECK (length(description) <= 500),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, slug),
    UNIQUE (agent_id, organization_id)
);

CREATE TABLE sentinel_tools (
    tool_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id),
    name TEXT NOT NULL CHECK (name ~ '^[a-z][a-z0-9_]{2,63}$'),
    version TEXT NOT NULL CHECK (version ~ '^[0-9]+\.[0-9]+\.[0-9]+$'),
    description TEXT NOT NULL CHECK (length(trim(description)) BETWEEN 1 AND 500),
    input_schema JSONB NOT NULL,
    output_schema JSONB NOT NULL,
    risk_level TEXT NOT NULL CHECK (risk_level IN ('low', 'medium', 'high')),
    approval_mode TEXT NOT NULL CHECK (approval_mode IN ('never', 'risk_based', 'always')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, name, version),
    UNIQUE (tool_id, organization_id),
    CHECK (risk_level <> 'high' OR approval_mode = 'always')
);

CREATE TABLE sentinel_agent_tools (
    agent_id UUID NOT NULL,
    tool_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    max_calls_per_run INTEGER NOT NULL CHECK (max_calls_per_run BETWEEN 1 AND 100),
    granted_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (agent_id, tool_id),
    FOREIGN KEY (agent_id, organization_id)
        REFERENCES sentinel_agents(agent_id, organization_id) ON DELETE CASCADE,
    FOREIGN KEY (tool_id, organization_id)
        REFERENCES sentinel_tools(tool_id, organization_id) ON DELETE CASCADE
);

CREATE TABLE sentinel_registry_events (
    event_id BIGSERIAL PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id),
    resource_type TEXT NOT NULL CHECK (resource_type IN ('agent', 'tool', 'agent_tool_grant')),
    resource_id UUID NOT NULL,
    event_type TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    actor_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX sentinel_agents_org_idx ON sentinel_agents (organization_id, created_at);
CREATE INDEX sentinel_tools_org_idx ON sentinel_tools (organization_id, name, version);
CREATE INDEX sentinel_registry_events_org_idx
    ON sentinel_registry_events (organization_id, event_id);
