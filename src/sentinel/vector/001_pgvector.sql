CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE estate_property_embeddings
    ADD COLUMN IF NOT EXISTS embedding_vector vector(512);

UPDATE estate_property_embeddings
SET embedding_vector = embedding::vector(512)
WHERE embedding_vector IS NULL;
