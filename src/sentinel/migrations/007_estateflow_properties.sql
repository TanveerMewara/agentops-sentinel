CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

CREATE TABLE estate_properties (
    property_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id),
    external_key TEXT NOT NULL CHECK (length(trim(external_key)) BETWEEN 1 AND 120),
    title TEXT NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 200),
    description TEXT NOT NULL CHECK (length(trim(description)) BETWEEN 1 AND 5000),
    city TEXT NOT NULL CHECK (length(trim(city)) BETWEEN 1 AND 100),
    locality TEXT NOT NULL CHECK (length(trim(locality)) BETWEEN 1 AND 150),
    property_type TEXT NOT NULL CHECK (
        property_type IN ('apartment', 'house', 'villa', 'plot', 'commercial')
    ),
    bedrooms INTEGER CHECK (bedrooms IS NULL OR bedrooms BETWEEN 0 AND 20),
    bathrooms NUMERIC(4,1) CHECK (bathrooms IS NULL OR bathrooms BETWEEN 0 AND 20),
    price_inr NUMERIC(16,2) NOT NULL CHECK (price_inr >= 0),
    area_sqft NUMERIC(12,2) CHECK (area_sqft IS NULL OR area_sqft > 0),
    amenities TEXT[] NOT NULL DEFAULT '{}',
    source_uri TEXT NOT NULL CHECK (length(trim(source_uri)) BETWEEN 1 AND 500),
    listing_status TEXT NOT NULL DEFAULT 'active'
        CHECK (listing_status IN ('active', 'reserved', 'sold', 'inactive')),
    content_hash TEXT NOT NULL,
    current_version INTEGER NOT NULL DEFAULT 1 CHECK (current_version > 0),
    created_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    search_vector TSVECTOR GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(city, '') || ' ' || coalesce(locality, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(description, '')), 'B')
    ) STORED,
    UNIQUE (organization_id, external_key),
    UNIQUE (property_id, organization_id)
);

CREATE TABLE estate_property_versions (
    property_version_id UUID PRIMARY KEY,
    property_id UUID NOT NULL,
    organization_id UUID NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    content_hash TEXT NOT NULL,
    snapshot JSONB NOT NULL,
    ingested_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (property_id, version),
    UNIQUE (property_id, content_hash),
    FOREIGN KEY (property_id, organization_id)
        REFERENCES estate_properties(property_id, organization_id) ON DELETE CASCADE
);

CREATE TABLE estate_retrieval_queries (
    retrieval_id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES sentinel_organizations(organization_id),
    query_text TEXT NOT NULL CHECK (length(query_text) BETWEEN 1 AND 500),
    filters JSONB NOT NULL DEFAULT '{}',
    strategy TEXT NOT NULL CHECK (strategy IN ('hybrid_lexical_v1')),
    result_evidence JSONB NOT NULL,
    created_by_key_id UUID NOT NULL REFERENCES sentinel_api_keys(api_key_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX estate_properties_search_idx ON estate_properties USING GIN (search_vector);
CREATE INDEX estate_properties_title_trgm_idx ON estate_properties USING GIN (title gin_trgm_ops);
CREATE INDEX estate_properties_org_filter_idx
    ON estate_properties (organization_id, listing_status, city, property_type, price_inr);
CREATE INDEX estate_property_versions_property_idx
    ON estate_property_versions (property_id, version DESC);
CREATE INDEX estate_retrieval_org_idx
    ON estate_retrieval_queries (organization_id, created_at DESC);
