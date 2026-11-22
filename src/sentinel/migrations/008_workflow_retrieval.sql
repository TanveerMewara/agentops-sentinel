ALTER TABLE estate_property_versions
    DROP CONSTRAINT estate_property_versions_property_id_content_hash_key;

ALTER TABLE estate_retrieval_queries
    ADD COLUMN run_id UUID,
    ADD COLUMN result_snapshot JSONB;

ALTER TABLE estate_retrieval_queries
    ADD CONSTRAINT estate_retrieval_run_fk
    FOREIGN KEY (run_id, organization_id)
    REFERENCES sentinel_runs(run_id, organization_id);

CREATE UNIQUE INDEX estate_retrieval_run_once_idx
    ON estate_retrieval_queries (run_id) WHERE run_id IS NOT NULL;

ALTER TABLE estate_retrieval_queries
    ADD CONSTRAINT estate_retrieval_snapshot_check
    CHECK (run_id IS NULL OR result_snapshot IS NOT NULL);
