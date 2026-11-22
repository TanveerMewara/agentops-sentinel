CREATE TABLE estate_crm_contacts (
    crm_contact_id UUID PRIMARY KEY,
    lead_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    stage TEXT NOT NULL CHECK (stage IN
        ('qualified', 'viewing_booked', 'nurture', 'human_review')),
    last_run_id UUID,
    booking_id TEXT,
    selected_property_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (lead_id),
    UNIQUE (crm_contact_id, organization_id),
    FOREIGN KEY (lead_id, organization_id)
        REFERENCES estate_leads(lead_id, organization_id) ON DELETE CASCADE,
    FOREIGN KEY (last_run_id, organization_id)
        REFERENCES sentinel_runs(run_id, organization_id),
    FOREIGN KEY (selected_property_id, organization_id)
        REFERENCES estate_properties(property_id, organization_id)
);

CREATE TABLE estate_followup_drafts (
    draft_id UUID PRIMARY KEY,
    lead_id UUID NOT NULL,
    run_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    channel TEXT NOT NULL CHECK (channel='email'),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved', 'cancelled')),
    encrypted_recipient BYTEA NOT NULL,
    encrypted_subject BYTEA NOT NULL,
    encrypted_body BYTEA NOT NULL,
    context_snapshot JSONB NOT NULL,
    created_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    approved_by_key_id UUID REFERENCES sentinel_api_keys(api_key_id),
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id),
    UNIQUE (draft_id, organization_id),
    FOREIGN KEY (lead_id, organization_id)
        REFERENCES estate_leads(lead_id, organization_id) ON DELETE CASCADE,
    FOREIGN KEY (run_id, organization_id)
        REFERENCES sentinel_runs(run_id, organization_id) ON DELETE CASCADE
);

CREATE TABLE estate_engagement_events (
    event_id BIGSERIAL PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id),
    lead_id UUID NOT NULL,
    run_id UUID,
    event_type TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}',
    actor_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (lead_id, organization_id)
        REFERENCES estate_leads(lead_id, organization_id) ON DELETE CASCADE
);

CREATE INDEX estate_crm_org_stage_idx
    ON estate_crm_contacts (organization_id, stage, updated_at DESC);
CREATE INDEX estate_followup_org_status_idx
    ON estate_followup_drafts (organization_id, status, created_at DESC);
