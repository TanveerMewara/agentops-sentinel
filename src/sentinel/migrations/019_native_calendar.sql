CREATE TABLE estate_calendar_slots (
    slot_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id),
    property_id UUID NOT NULL,
    property_version INTEGER NOT NULL CHECK (property_version > 0),
    starts_at TIMESTAMPTZ NOT NULL,
    ends_at TIMESTAMPTZ NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (ends_at >= starts_at + interval '5 minutes' AND ends_at <= starts_at + interval '4 hours'),
    UNIQUE (slot_id, organization_id),
    UNIQUE (organization_id, property_id, property_version, starts_at, ends_at),
    FOREIGN KEY (property_id, organization_id) REFERENCES estate_properties(property_id, organization_id)
);
CREATE TABLE estate_calendar_reservations (
    reservation_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id),
    slot_id UUID NOT NULL,
    run_id UUID NOT NULL REFERENCES sentinel_runs(run_id),
    status TEXT NOT NULL CHECK (status IN ('confirmed', 'cancelled')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    cancelled_at TIMESTAMPTZ,
    FOREIGN KEY (slot_id, organization_id) REFERENCES estate_calendar_slots(slot_id, organization_id),
    UNIQUE (reservation_id, organization_id)
);
CREATE TABLE estate_calendar_decisions (
    decision_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id),
    tool_call_id UUID NOT NULL REFERENCES sentinel_tool_calls(tool_call_id),
    run_id UUID NOT NULL REFERENCES sentinel_runs(run_id),
    action TEXT NOT NULL CHECK (action IN ('reserve', 'cancel')),
    arguments_hash TEXT NOT NULL,
    result JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, tool_call_id)
);
CREATE INDEX estate_calendar_slots_resource_idx ON estate_calendar_slots(organization_id, property_id, starts_at, ends_at);
CREATE INDEX estate_calendar_reservations_slot_idx ON estate_calendar_reservations(organization_id, slot_id, status);
