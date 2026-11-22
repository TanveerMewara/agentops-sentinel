ALTER TABLE sentinel_api_keys ADD COLUMN expires_at TIMESTAMPTZ;
CREATE TABLE sentinel_access_events (
    event_id BIGSERIAL PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id),
    target_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    actor_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    event_type TEXT NOT NULL CHECK (event_type IN ('key.created', 'key.revoked')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX sentinel_access_events_org_idx ON sentinel_access_events(organization_id, event_id);
