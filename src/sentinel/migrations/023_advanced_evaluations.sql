ALTER TABLE sentinel_evaluation_experiments
    ADD CONSTRAINT sentinel_evaluation_experiments_id_org_unique
    UNIQUE (experiment_id,organization_id);

CREATE TABLE sentinel_evaluation_human_labels (
    human_label_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id) ON DELETE CASCADE,
    dataset_id UUID NOT NULL,
    case_key TEXT NOT NULL,
    run_id UUID NOT NULL,
    score NUMERIC(5,4) NOT NULL CHECK (score BETWEEN 0 AND 1),
    label TEXT NOT NULL CHECK (label IN ('pass','fail')),
    reviewer_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id,dataset_id,case_key,run_id,reviewer_key_id),
    FOREIGN KEY (dataset_id,organization_id)
        REFERENCES sentinel_evaluation_datasets(dataset_id,organization_id) ON DELETE CASCADE,
    FOREIGN KEY (run_id,organization_id)
        REFERENCES sentinel_runs(run_id,organization_id) ON DELETE CASCADE
);

CREATE TABLE sentinel_evaluation_calibrations (
    calibration_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id) ON DELETE CASCADE,
    dataset_id UUID NOT NULL,
    experiment_id UUID NOT NULL,
    config_hash TEXT NOT NULL CHECK (config_hash ~ '^[0-9a-f]{64}$'),
    report JSONB NOT NULL CHECK (jsonb_typeof(report)='object'),
    created_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id,config_hash),
    FOREIGN KEY (dataset_id,organization_id)
        REFERENCES sentinel_evaluation_datasets(dataset_id,organization_id),
    FOREIGN KEY (experiment_id,organization_id)
        REFERENCES sentinel_evaluation_experiments(experiment_id,organization_id)
);

CREATE TABLE sentinel_evaluation_release_gates (
    release_gate_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id) ON DELETE CASCADE,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    report JSONB NOT NULL CHECK (jsonb_typeof(report)='object'),
    created_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id,idempotency_key)
);

CREATE TABLE sentinel_evaluation_sampling_policies (
    organization_id UUID PRIMARY KEY REFERENCES sentinel_organizations(organization_id) ON DELETE CASCADE,
    dataset_id UUID NOT NULL,
    case_key TEXT NOT NULL,
    sample_rate NUMERIC(6,5) NOT NULL CHECK (sample_rate BETWEEN 0 AND 1),
    daily_limit INTEGER NOT NULL CHECK (daily_limit BETWEEN 1 AND 10000),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    updated_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (dataset_id,organization_id)
        REFERENCES sentinel_evaluation_datasets(dataset_id,organization_id)
);

CREATE TABLE sentinel_evaluation_online_samples (
    online_sample_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id) ON DELETE CASCADE,
    run_id UUID NOT NULL,
    dataset_id UUID NOT NULL,
    selected BOOLEAN NOT NULL,
    experiment_id UUID,
    sampled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id,run_id),
    FOREIGN KEY (run_id,organization_id)
        REFERENCES sentinel_runs(run_id,organization_id) ON DELETE CASCADE,
    FOREIGN KEY (dataset_id,organization_id)
        REFERENCES sentinel_evaluation_datasets(dataset_id,organization_id),
    FOREIGN KEY (experiment_id,organization_id)
        REFERENCES sentinel_evaluation_experiments(experiment_id,organization_id)
);
