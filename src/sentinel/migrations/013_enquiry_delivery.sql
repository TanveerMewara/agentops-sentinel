CREATE TABLE estate_enquiry_sources (
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id),
    external_key TEXT NOT NULL,
    last_sequence BIGINT NOT NULL DEFAULT 0 CHECK (last_sequence >= 0),
    PRIMARY KEY (organization_id, external_key)
);

CREATE TABLE estate_enquiry_deliveries (
    delivery_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id),
    delivery_key TEXT NOT NULL,
    external_key TEXT NOT NULL,
    source_sequence BIGINT NOT NULL CHECK (source_sequence > 0),
    payload_hash TEXT NOT NULL,
    lead_id UUID NOT NULL,
    receipt JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, delivery_key),
    UNIQUE (organization_id, external_key, source_sequence),
    FOREIGN KEY (lead_id, organization_id)
        REFERENCES estate_leads(lead_id, organization_id)
);
CREATE INDEX estate_enquiry_deliveries_org_idx
    ON estate_enquiry_deliveries (organization_id, created_at DESC);
