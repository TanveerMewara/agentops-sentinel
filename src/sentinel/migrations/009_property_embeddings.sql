ALTER TABLE estate_property_versions
    ADD CONSTRAINT estate_property_versions_identity_unique
    UNIQUE (property_version_id, property_id, organization_id);

CREATE TABLE estate_property_embeddings (
    embedding_id UUID PRIMARY KEY,
    property_version_id UUID NOT NULL,
    property_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    model_alias TEXT NOT NULL CHECK (model_alias ~ '^[a-z][a-z0-9_-]{2,63}$'),
    provider TEXT NOT NULL CHECK (provider = 'openai'),
    model_id TEXT NOT NULL CHECK (model_id = 'text-embedding-3-small'),
    dimensions INTEGER NOT NULL CHECK (dimensions = 512),
    source_hash TEXT NOT NULL CHECK (length(source_hash) = 64),
    embedding REAL[] NOT NULL CHECK (array_length(embedding, 1) = 512),
    input_tokens INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (property_version_id, model_alias, model_id),
    FOREIGN KEY (property_version_id, property_id, organization_id)
        REFERENCES estate_property_versions(property_version_id, property_id, organization_id)
        ON DELETE CASCADE
);

CREATE INDEX estate_embeddings_current_idx
    ON estate_property_embeddings (organization_id, model_alias, model_id, property_id);

CREATE TABLE estate_embedding_invocations (
    invocation_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id),
    model_alias TEXT NOT NULL,
    model_id TEXT NOT NULL,
    purpose TEXT NOT NULL CHECK (purpose IN ('property_backfill', 'property_query')),
    status TEXT NOT NULL CHECK (status IN ('succeeded', 'failed')),
    input_count INTEGER NOT NULL CHECK (input_count BETWEEN 1 AND 10),
    input_tokens INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    duration_ms INTEGER NOT NULL CHECK (duration_ms >= 0),
    error_class TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX estate_embedding_invocations_org_idx
    ON estate_embedding_invocations (organization_id, created_at DESC);

ALTER TABLE estate_retrieval_queries
    DROP CONSTRAINT estate_retrieval_queries_strategy_check;
ALTER TABLE estate_retrieval_queries
    ADD CONSTRAINT estate_retrieval_strategy_check
    CHECK (strategy IN ('hybrid_lexical_v1', 'vector_array_exact_v1',
                       'vector_pgvector_exact_v1'));
ALTER TABLE estate_retrieval_queries
    ADD COLUMN embedding_model_alias TEXT,
    ADD COLUMN embedding_model_id TEXT,
    ADD COLUMN embedding_backend TEXT;
