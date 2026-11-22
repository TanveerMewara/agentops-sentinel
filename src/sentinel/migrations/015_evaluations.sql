CREATE TABLE sentinel_evaluation_datasets (
    dataset_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id),
    slug TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    definition JSONB NOT NULL,
    content_hash TEXT NOT NULL,
    created_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, slug, version),
    UNIQUE (dataset_id, organization_id)
);
CREATE TABLE sentinel_evaluation_experiments (
    experiment_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id),
    dataset_id UUID NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    report JSONB NOT NULL,
    created_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, idempotency_key),
    FOREIGN KEY (dataset_id, organization_id)
        REFERENCES sentinel_evaluation_datasets(dataset_id, organization_id)
);
CREATE INDEX sentinel_evaluation_experiments_org_idx
    ON sentinel_evaluation_experiments (organization_id, created_at DESC);
