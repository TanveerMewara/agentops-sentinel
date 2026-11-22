CREATE TABLE estate_leads (
    lead_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id),
    external_key TEXT NOT NULL CHECK (length(trim(external_key)) BETWEEN 1 AND 120),
    channel TEXT NOT NULL CHECK (channel IN ('manual', 'website')),
    encrypted_customer_name BYTEA NOT NULL,
    encrypted_contact_email BYTEA,
    city TEXT CHECK (city IS NULL OR length(trim(city)) BETWEEN 1 AND 100),
    max_budget_inr NUMERIC(16,2) CHECK (max_budget_inr IS NULL OR max_budget_inr > 0),
    min_bedrooms INTEGER CHECK (min_bedrooms IS NULL OR min_bedrooms BETWEEN 0 AND 20),
    timeline TEXT NOT NULL CHECK (timeline IN ('unknown', 'within_month', 'within_quarter', 'later')),
    outreach_consent BOOLEAN NOT NULL,
    human_help_requested BOOLEAN NOT NULL,
    qualification_status TEXT NOT NULL CHECK (qualification_status IN
        ('needs_information', 'qualified', 'nurture', 'human_review')),
    qualification_reasons JSONB NOT NULL,
    content_hash TEXT NOT NULL,
    current_version INTEGER NOT NULL DEFAULT 1 CHECK (current_version > 0),
    created_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, external_key),
    UNIQUE (lead_id, organization_id)
);

CREATE TABLE estate_lead_versions (
    lead_version_id UUID PRIMARY KEY,
    lead_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    content_hash TEXT NOT NULL,
    requirements JSONB NOT NULL,
    qualification_status TEXT NOT NULL,
    qualification_reasons JSONB NOT NULL,
    created_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (lead_id, version),
    FOREIGN KEY (lead_id, organization_id)
        REFERENCES estate_leads(lead_id, organization_id) ON DELETE CASCADE
);

CREATE TABLE estate_lead_events (
    event_id BIGSERIAL PRIMARY KEY,
    lead_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    event_type TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}',
    actor_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (lead_id, organization_id)
        REFERENCES estate_leads(lead_id, organization_id) ON DELETE CASCADE
);

CREATE INDEX estate_leads_org_status_idx
    ON estate_leads (organization_id, qualification_status, updated_at DESC);
CREATE INDEX estate_lead_events_lead_idx ON estate_lead_events (lead_id, event_id);
