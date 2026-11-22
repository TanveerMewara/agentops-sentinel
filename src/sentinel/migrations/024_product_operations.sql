ALTER TABLE sentinel_api_keys ADD COLUMN key_kind TEXT NOT NULL DEFAULT 'service'
    CHECK (key_kind IN ('service','member_actor'));

CREATE TABLE sentinel_organization_profiles (
    organization_id UUID PRIMARY KEY REFERENCES sentinel_organizations(organization_id) ON DELETE CASCADE,
    slug TEXT NOT NULL UNIQUE CHECK (slug ~ '^[a-z][a-z0-9-]{2,49}$'),
    display_name TEXT NOT NULL CHECK (length(trim(display_name)) BETWEEN 2 AND 100),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sentinel_members (
    member_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id) ON DELETE CASCADE,
    handle TEXT NOT NULL CHECK (handle ~ '^[a-z][a-z0-9_.-]{2,63}$'),
    display_name TEXT NOT NULL CHECK (length(trim(display_name)) BETWEEN 2 AND 100),
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin','developer','reviewer')),
    actor_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id,handle),
    UNIQUE (member_id,organization_id)
);

CREATE TABLE sentinel_member_invitations (
    invitation_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id) ON DELETE CASCADE,
    handle TEXT NOT NULL CHECK (handle ~ '^[a-z][a-z0-9_.-]{2,63}$'),
    role TEXT NOT NULL CHECK (role IN ('admin','developer','reviewer')),
    token_digest TEXT NOT NULL UNIQUE CHECK (token_digest ~ '^[0-9a-f]{64}$'),
    expires_at TIMESTAMPTZ NOT NULL,
    accepted_at TIMESTAMPTZ,
    created_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id,handle)
);

CREATE TABLE sentinel_member_sessions (
    session_id UUID PRIMARY KEY,
    member_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    token_digest TEXT NOT NULL UNIQUE CHECK (token_digest ~ '^[0-9a-f]{64}$'),
    csrf_digest TEXT NOT NULL CHECK (csrf_digest ~ '^[0-9a-f]{64}$'),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (member_id,organization_id)
        REFERENCES sentinel_members(member_id,organization_id) ON DELETE CASCADE
);

CREATE INDEX sentinel_member_sessions_expiry ON sentinel_member_sessions(expires_at);

CREATE TABLE sentinel_preauth_limits (
    identity_hash TEXT NOT NULL CHECK (identity_hash ~ '^[0-9a-f]{64}$'),
    route TEXT NOT NULL,
    window_started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    request_count INTEGER NOT NULL DEFAULT 1 CHECK (request_count>0),
    PRIMARY KEY(identity_hash,route)
);

CREATE TABLE sentinel_alert_policies (
    organization_id UUID PRIMARY KEY REFERENCES sentinel_organizations(organization_id) ON DELETE CASCADE,
    telemetry_incomplete BOOLEAN NOT NULL DEFAULT TRUE,
    release_gate_failed BOOLEAN NOT NULL DEFAULT TRUE,
    failed_run_threshold INTEGER NOT NULL DEFAULT 3 CHECK (failed_run_threshold BETWEEN 1 AND 1000),
    updated_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sentinel_alerts (
    alert_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id) ON DELETE CASCADE,
    alert_type TEXT NOT NULL CHECK (alert_type IN ('telemetry_incomplete','release_gate_failed','failed_runs')),
    severity TEXT NOT NULL CHECK (severity IN ('warning','critical')),
    reference_id TEXT NOT NULL,
    summary JSONB NOT NULL CHECK (jsonb_typeof(summary)='object'),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','acknowledged','resolved')),
    acknowledged_by_key_id UUID REFERENCES sentinel_api_keys(api_key_id),
    acknowledged_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id,alert_type,reference_id)
);

CREATE TABLE sentinel_deployment_environments (
    environment_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id) ON DELETE CASCADE,
    slug TEXT NOT NULL CHECK (slug ~ '^[a-z][a-z0-9_-]{2,49}$'),
    display_name TEXT NOT NULL CHECK (length(trim(display_name)) BETWEEN 2 AND 100),
    created_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id,slug),
    UNIQUE (environment_id,organization_id)
);

ALTER TABLE sentinel_evaluation_release_gates
    ADD CONSTRAINT sentinel_evaluation_release_gates_id_org_unique
    UNIQUE (release_gate_id,organization_id);

CREATE TABLE sentinel_deployment_records (
    deployment_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id) ON DELETE CASCADE,
    environment_id UUID NOT NULL,
    release_gate_id UUID NOT NULL,
    artifact_digest TEXT NOT NULL CHECK (artifact_digest ~ '^[0-9a-f]{64}$'),
    version TEXT NOT NULL CHECK (version ~ '^[a-zA-Z0-9_.-]{1,80}$'),
    status TEXT NOT NULL CHECK (status IN ('approved','deployed','failed','rolled_back')),
    created_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    deployed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id,environment_id,version),
    FOREIGN KEY (environment_id,organization_id)
        REFERENCES sentinel_deployment_environments(environment_id,organization_id),
    FOREIGN KEY (release_gate_id,organization_id)
        REFERENCES sentinel_evaluation_release_gates(release_gate_id,organization_id)
);

CREATE TABLE sentinel_lab_campaigns (
    campaign_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id) ON DELETE CASCADE,
    campaign_type TEXT NOT NULL CHECK (campaign_type IN ('fault','security')),
    profile TEXT NOT NULL CHECK (profile IN ('boundary','recovery','full')),
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','passed','failed')),
    report JSONB CHECK (report IS NULL OR jsonb_typeof(report)='object'),
    report_hash TEXT CHECK (report_hash IS NULL OR report_hash ~ '^[0-9a-f]{64}$'),
    created_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    claimed_by_key_id UUID REFERENCES sentinel_api_keys(api_key_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);
