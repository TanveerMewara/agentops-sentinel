"""Versioned property embeddings and exact vector retrieval."""
import hashlib
import math
from time import monotonic
from uuid import uuid4

from fastapi import HTTPException
from openai import OpenAI
from psycopg.types.json import Jsonb

from .properties import _evidence, property_view
from .provider_registry import CredentialCipher, get_model_credential
from .schemas import (
    PropertyEmbeddingBackfill, PropertySearch, PropertySearchResponse,
)
from .security import Principal, require_roles


MODEL_ID = "text-embedding-3-small"
DIMENSIONS = 512
ARRAY_CANDIDATE_LIMIT = 500


def embedding_text(snapshot: dict) -> str:
    return "\n".join((
        f"Title: {snapshot['title']}",
        f"Location: {snapshot['locality']}, {snapshot['city']}",
        f"Type: {snapshot['property_type']}",
        f"Description: {snapshot['description'][:2400]}",
        f"Amenities: {', '.join(snapshot['amenities'])}",
    ))


def embedding_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def validate_embedding(values) -> list[float]:
    if not isinstance(values, (list, tuple)) or len(values) != DIMENSIONS:
        raise ValueError(f"Embedding must contain exactly {DIMENSIONS} values.")
    vector = [float(value) for value in values]
    if not all(math.isfinite(value) for value in vector):
        raise ValueError("Embedding contains a non-finite value.")
    if math.fsum(value * value for value in vector) == 0:
        raise ValueError("Embedding cannot be the zero vector.")
    return vector


def cosine_similarity(left: list[float], right: list[float]) -> float:
    numerator = math.fsum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(math.fsum(value * value for value in left))
    right_norm = math.sqrt(math.fsum(value * value for value in right))
    return numerator / (left_norm * right_norm)


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(format(value, ".9g") for value in values) + "]"


def _vector_ready(connection) -> bool:
    return connection.execute(
        """SELECT EXISTS (
             SELECT 1 FROM information_schema.columns
             WHERE table_name='estate_property_embeddings'
               AND column_name='embedding_vector'
           ) AS ready"""
    ).fetchone()["ready"]


def _filter_sql(body: PropertySearch, organization_id: str) -> tuple[list[str], list]:
    clauses = ["p.organization_id=%s", "p.listing_status='active'"]
    values: list = [organization_id]
    for clause, value in (
        ("lower(p.city)=lower(%s)", body.city),
        ("p.property_type=%s", body.property_type),
        ("p.bedrooms >= %s", body.min_bedrooms),
        ("p.price_inr <= %s", body.max_price_inr),
    ):
        if value is not None:
            clauses.append(clause)
            values.append(value)
    if body.required_amenities:
        clauses.append("p.amenities @> %s::text[]")
        values.append(body.required_amenities)
    return clauses, values


class EmbeddingService:
    def __init__(self, database, cipher: CredentialCipher, timeout_seconds: int = 20,
                 client_factory=OpenAI):
        self.database = database
        self.cipher = cipher
        self.timeout_seconds = timeout_seconds
        self.client_factory = client_factory

    def _credential(self, principal: Principal, model_alias: str) -> dict:
        credential = get_model_credential(
            self.database, self.cipher, principal.organization_id, model_alias
        )
        if credential["model_id"] != MODEL_ID:
            raise HTTPException(
                409, f"Embedding alias '{model_alias}' must use {MODEL_ID}."
            )
        return credential

    def _record_invocation(self, principal: Principal, alias: str, purpose: str,
                           count: int, tokens: int, duration_ms: int,
                           status: str, error_class: str | None = None) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """INSERT INTO estate_embedding_invocations
                   (invocation_id, organization_id, model_alias, model_id, purpose,
                    status, input_count, input_tokens, duration_ms, error_class)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (uuid4(), principal.organization_id, alias, MODEL_ID, purpose,
                 status, count, tokens, duration_ms, error_class),
            )

    def _embed(self, principal: Principal, credential: dict,
               inputs: list[str], purpose: str) -> list[list[float]]:
        started = monotonic()
        tokens = 0
        try:
            client = self.client_factory(
                api_key=credential["api_key"], timeout=self.timeout_seconds,
                max_retries=0,
            )
            response = client.embeddings.create(
                model=MODEL_ID, input=inputs, dimensions=DIMENSIONS,
                encoding_format="float",
            )
            tokens = int(getattr(getattr(response, "usage", None), "total_tokens", 0))
            by_index = {item.index: item.embedding for item in response.data}
            if (len(response.data) != len(inputs)
                    or set(by_index) != set(range(len(inputs)))):
                raise ValueError("Embedding response has missing or duplicate indexes.")
            vectors = [validate_embedding(by_index[index]) for index in range(len(inputs))]
        except Exception as error:
            self._record_invocation(
                principal, credential["model_alias"], purpose, len(inputs), tokens,
                max(0, int((monotonic() - started) * 1000)), "failed",
                type(error).__name__,
            )
            raise HTTPException(502, "Embedding provider failed or returned invalid data.") from error
        self._record_invocation(
            principal, credential["model_alias"], purpose, len(inputs), tokens,
            max(0, int((monotonic() - started) * 1000)), "succeeded",
        )
        return vectors

    def _remaining(self, connection, principal: Principal,
                   alias: str, external_key_prefix: str | None) -> int:
        return connection.execute(
            """SELECT count(*) AS remaining FROM estate_properties p
               JOIN estate_property_versions v
                 ON v.property_id=p.property_id AND v.version=p.current_version
               LEFT JOIN estate_property_embeddings e
                 ON e.property_version_id=v.property_version_id
                AND e.model_alias=%s AND e.model_id=%s
               WHERE p.organization_id=%s AND p.listing_status='active'
                 AND (%s::text IS NULL OR left(p.external_key, length(%s::text))=%s::text)
                 AND e.embedding_id IS NULL""",
            (alias, MODEL_ID, principal.organization_id,
             external_key_prefix, external_key_prefix, external_key_prefix),
        ).fetchone()["remaining"]

    def backfill(self, principal: Principal,
                 body: PropertyEmbeddingBackfill) -> dict:
        require_roles("admin")(principal)
        credential = self._credential(principal, body.model_alias)
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT p.property_id, v.property_version_id, v.snapshot
                   FROM estate_properties p
                   JOIN estate_property_versions v
                     ON v.property_id=p.property_id AND v.version=p.current_version
                   LEFT JOIN estate_property_embeddings e
                     ON e.property_version_id=v.property_version_id
                    AND e.model_alias=%s AND e.model_id=%s
                   WHERE p.organization_id=%s AND p.listing_status='active'
                     AND (%s::text IS NULL OR left(p.external_key, length(%s::text))=%s::text)
                     AND e.embedding_id IS NULL
                   ORDER BY p.updated_at, p.property_id LIMIT %s""",
                (body.model_alias, MODEL_ID, principal.organization_id,
                 body.external_key_prefix, body.external_key_prefix,
                 body.external_key_prefix, body.limit),
            ).fetchall()
            if not rows:
                return {"model_alias": body.model_alias, "model_id": MODEL_ID,
                        "embedded": 0, "skipped": 0, "remaining": 0}
        texts = [embedding_text(row["snapshot"]) for row in rows]
        vectors = self._embed(principal, credential, texts, "property_backfill")
        embedded = 0
        with self.database.connect() as connection:
            vector_ready = _vector_ready(connection)
            for row, text_value, vector in zip(rows, texts, vectors, strict=True):
                result = connection.execute(
                    """INSERT INTO estate_property_embeddings
                       (embedding_id, property_version_id, property_id,
                        organization_id, model_alias, provider, model_id,
                        dimensions, source_hash, embedding, input_tokens)
                       VALUES (%s, %s, %s, %s, %s, 'openai', %s, %s, %s, %s, 0)
                       ON CONFLICT DO NOTHING RETURNING embedding_id""",
                    (uuid4(), row["property_version_id"], row["property_id"],
                     principal.organization_id, body.model_alias, MODEL_ID,
                     DIMENSIONS, embedding_hash(text_value), vector),
                ).fetchone()
                if result is not None:
                    embedded += 1
                    if vector_ready:
                        connection.execute(
                            """UPDATE estate_property_embeddings
                               SET embedding_vector=embedding::vector(512)
                               WHERE embedding_id=%s""",
                            (result["embedding_id"],),
                        )
            remaining = self._remaining(
                connection, principal, body.model_alias, body.external_key_prefix
            )
        return {"model_alias": body.model_alias, "model_id": MODEL_ID,
                "embedded": embedded, "skipped": len(rows) - embedded,
                "remaining": remaining}

    def _saved(self, connection, principal: Principal, run_id: str,
               body: PropertySearch, filters: dict) -> dict | None:
        run = connection.execute(
            """SELECT run_id FROM sentinel_runs
               WHERE run_id=%s AND organization_id=%s FOR UPDATE""",
            (run_id, principal.organization_id),
        ).fetchone()
        if run is None:
            raise HTTPException(404, "Run not found.")
        existing = connection.execute(
            """SELECT query_text, filters, strategy, embedding_model_alias,
                      result_snapshot FROM estate_retrieval_queries
               WHERE run_id=%s AND organization_id=%s""",
            (run_id, principal.organization_id),
        ).fetchone()
        if existing is None:
            return None
        if (existing["query_text"] != body.query or existing["filters"] != filters
                or existing["strategy"] not in (
                    "vector_array_exact_v1", "vector_pgvector_exact_v1"
                ) or existing["embedding_model_alias"] != body.embedding_model_alias):
            raise HTTPException(409, "Run retrieval input has changed.")
        return existing["result_snapshot"]

    def search(self, principal: Principal, body: PropertySearch,
               run_id: str | None = None) -> dict:
        require_roles("admin", "developer", "worker")(principal)
        filters = body.model_dump(
            mode="json", exclude={"query", "strategy", "embedding_model_alias"},
            exclude_none=True,
        )
        if run_id is not None:
            with self.database.connect() as connection:
                saved = self._saved(connection, principal, run_id, body, filters)
                if saved is not None:
                    return saved
        credential = self._credential(principal, body.embedding_model_alias)
        clauses, values = _filter_sql(body, principal.organization_id)
        join = """FROM estate_properties p
            JOIN estate_property_versions v
              ON v.property_id=p.property_id AND v.version=p.current_version
            LEFT JOIN estate_property_embeddings e
              ON e.property_version_id=v.property_version_id
             AND e.model_alias=%s AND e.model_id=%s"""
        where = " AND ".join(clauses)
        parameters = [body.embedding_model_alias, MODEL_ID, *values]
        with self.database.connect() as connection:
            vector_ready = _vector_ready(connection)
            missing_condition = "e.embedding_id IS NULL"
            if vector_ready:
                missing_condition += " OR e.embedding_vector IS NULL"
            coverage = connection.execute(
                f"""SELECT count(*) AS total,
                           count(*) FILTER (WHERE {missing_condition}) AS missing
                    {join} WHERE {where}""",
                parameters,
            ).fetchone()
        if coverage["missing"]:
            raise HTTPException(
                409, "Active matching properties need an embedding backfill first."
            )
        if not vector_ready and coverage["total"] > ARRAY_CANDIDATE_LIMIT:
            raise HTTPException(
                409, "Array vector search exceeds 500 candidates; enable pgvector."
            )
        strategy = (
            "vector_pgvector_exact_v1" if vector_ready else "vector_array_exact_v1"
        )
        scored = []
        if coverage["total"]:
            query_vector = self._embed(
                principal, credential, [body.query], "property_query"
            )[0]
            with self.database.connect() as connection:
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                vector_ready = _vector_ready(connection)
                missing_condition = "e.embedding_id IS NULL"
                if vector_ready:
                    missing_condition += " OR e.embedding_vector IS NULL"
                coverage = connection.execute(
                    f"""SELECT count(*) AS total,
                               count(*) FILTER (WHERE {missing_condition}) AS missing
                        {join} WHERE {where}""",
                    parameters,
                ).fetchone()
                if coverage["missing"]:
                    raise HTTPException(
                        409, "Active matching properties need an embedding backfill first."
                    )
                if not vector_ready and coverage["total"] > ARRAY_CANDIDATE_LIMIT:
                    raise HTTPException(
                        409, "Array vector search exceeds 500 candidates; enable pgvector."
                    )
                strategy = (
                    "vector_pgvector_exact_v1" if vector_ready
                    else "vector_array_exact_v1"
                )
                if vector_ready:
                    literal = vector_literal(query_vector)
                    rows = connection.execute(
                        f"""SELECT p.*, e.embedding_id, e.model_id, e.source_hash,
                                   1 - (e.embedding_vector <=> %s::vector(512))
                                     AS retrieval_score
                            {join} WHERE {where}
                            ORDER BY e.embedding_vector <=> %s::vector(512),
                                     p.property_id LIMIT %s""",
                        [literal, *parameters, literal, body.limit],
                    ).fetchall()
                    scored = [(row, float(row["retrieval_score"])) for row in rows]
                else:
                    rows = connection.execute(
                        f"""SELECT p.*, e.embedding, e.embedding_id, e.model_id,
                                   e.source_hash {join} WHERE {where}
                            ORDER BY p.property_id LIMIT %s""",
                        [*parameters, ARRAY_CANDIDATE_LIMIT + 1],
                    ).fetchall()
                    scored = sorted(
                        ((row, cosine_similarity(query_vector, row["embedding"]))
                         for row in rows),
                        key=lambda item: (-item[1], str(item[0]["property_id"])),
                    )[:body.limit]
        results = []
        evidence_log = []
        for row, score_value in scored:
            evidence = _evidence(row, body, filters)
            evidence.update({
                "embedding_id": str(row["embedding_id"]),
                "embedding_model_id": MODEL_ID,
                "embedding_source_hash": row["source_hash"],
            })
            score = round(score_value, 6)
            results.append({
                "property": property_view(row), "score": score, "evidence": evidence,
            })
            evidence_log.append({
                "property_id": str(row["property_id"]), "score": score,
                **evidence,
            })
        retrieval_id = uuid4()
        response = PropertySearchResponse.model_validate({
            "retrieval_id": retrieval_id, "strategy": strategy,
            "embedding_model_id": MODEL_ID, "results": results,
        }).model_dump(mode="json")
        with self.database.connect() as connection:
            if run_id is not None:
                saved = self._saved(connection, principal, run_id, body, filters)
                if saved is not None:
                    return saved
            connection.execute(
                """INSERT INTO estate_retrieval_queries
                   (retrieval_id, organization_id, query_text, filters, strategy,
                    result_evidence, created_by_key_id, run_id, result_snapshot,
                    embedding_model_alias, embedding_model_id, embedding_backend)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (retrieval_id, principal.organization_id, body.query, Jsonb(filters),
                 strategy, Jsonb(evidence_log), principal.api_key_id, run_id,
                 Jsonb(response) if run_id is not None else None,
                 body.embedding_model_alias, MODEL_ID,
                 "pgvector" if vector_ready else "postgres_array"),
            )
        return response
