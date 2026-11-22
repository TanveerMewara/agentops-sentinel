import hashlib
import json
import re
from uuid import uuid4

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from .schemas import PropertySearch, PropertySearchResponse, PropertyUpsert
from .security import Principal


PROPERTY_FIELDS = (
    "property_id", "external_key", "title", "description", "city", "locality",
    "property_type", "bedrooms", "bathrooms", "price_inr", "area_sqft",
    "amenities", "source_uri", "listing_status", "current_version", "created_at",
    "updated_at",
)


def property_view(row: dict) -> dict:
    return {key: row[key] for key in PROPERTY_FIELDS}


def property_snapshot(body: PropertyUpsert) -> dict:
    return body.model_dump(mode="json")


def property_hash(snapshot: dict) -> str:
    encoded = json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _upsert(connection, principal: Principal, body: PropertyUpsert) -> tuple[dict, str]:
    snapshot = property_snapshot(body)
    content_hash = property_hash(snapshot)
    property_id = uuid4()
    row = connection.execute(
        """INSERT INTO estate_properties
           (property_id, organization_id, external_key, title, description, city,
            locality, property_type, bedrooms, bathrooms, price_inr, area_sqft,
            amenities, source_uri, listing_status, content_hash, created_by_key_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   %s, %s, %s)
           ON CONFLICT (organization_id, external_key) DO NOTHING RETURNING *""",
        (
            property_id, principal.organization_id, body.external_key, body.title,
            body.description, body.city, body.locality, body.property_type,
            body.bedrooms, body.bathrooms, body.price_inr, body.area_sqft,
            body.amenities, body.source_uri, body.listing_status, content_hash,
            principal.api_key_id,
        ),
    ).fetchone()
    if row is not None:
        action = "created"
    else:
        row = connection.execute(
            """SELECT * FROM estate_properties
               WHERE organization_id=%s AND external_key=%s FOR UPDATE""",
            (principal.organization_id, body.external_key),
        ).fetchone()
        if row["content_hash"] == content_hash:
            return property_view(row), "unchanged"
        row = connection.execute(
            """UPDATE estate_properties SET
                   title=%s, description=%s, city=%s, locality=%s, property_type=%s,
                   bedrooms=%s, bathrooms=%s, price_inr=%s, area_sqft=%s,
                   amenities=%s, source_uri=%s, listing_status=%s, content_hash=%s,
                   current_version=current_version+1, updated_at=now()
               WHERE property_id=%s RETURNING *""",
            (
                body.title, body.description, body.city, body.locality,
                body.property_type, body.bedrooms, body.bathrooms, body.price_inr,
                body.area_sqft, body.amenities, body.source_uri, body.listing_status,
                content_hash, row["property_id"],
            ),
        ).fetchone()
        action = "updated"
    connection.execute(
        """INSERT INTO estate_property_versions
           (property_version_id, property_id, organization_id, version, content_hash,
            snapshot, ingested_by_key_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
        (uuid4(), row["property_id"], principal.organization_id,
         row["current_version"], content_hash, Jsonb(snapshot), principal.api_key_id),
    )
    return property_view(row), action


def upsert_property(database, principal: Principal,
                    body: PropertyUpsert) -> tuple[dict, str]:
    with database.connect() as connection:
        return _upsert(connection, principal, body)


def upsert_property_batch(database, principal: Principal,
                          bodies: list[PropertyUpsert]) -> list[dict]:
    with database.connect() as connection:
        return [
            {"property": row, "outcome": outcome}
            for row, outcome in (_upsert(connection, principal, body) for body in bodies)
        ]


def list_properties(database, principal: Principal, limit: int, city: str | None,
                    property_type: str | None, listing_status: str | None) -> list[dict]:
    clauses = ["organization_id=%s"]
    parameters: list = [principal.organization_id]
    for column, value in (
        ("city", city), ("property_type", property_type), ("listing_status", listing_status)
    ):
        if value is not None:
            clauses.append(f"{column}=%s")
            parameters.append(value)
    parameters.append(limit)
    with database.connect() as connection:
        rows = connection.execute(
            f"""SELECT * FROM estate_properties WHERE {' AND '.join(clauses)}
                 ORDER BY updated_at DESC, property_id LIMIT %s""",
            parameters,
        ).fetchall()
    return [property_view(row) for row in rows]


def get_property(database, principal: Principal, property_id: str) -> dict:
    with database.connect() as connection:
        row = connection.execute(
            """SELECT * FROM estate_properties
               WHERE property_id=%s AND organization_id=%s""",
            (property_id, principal.organization_id),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Property not found.")
    return property_view(row)


def list_property_versions(database, principal: Principal, property_id: str) -> list[dict]:
    with database.connect() as connection:
        exists = connection.execute(
            """SELECT property_id FROM estate_properties
               WHERE property_id=%s AND organization_id=%s""",
            (property_id, principal.organization_id),
        ).fetchone()
        if exists is None:
            raise HTTPException(404, "Property not found.")
        return connection.execute(
            """SELECT property_version_id, property_id, version, content_hash,
                      snapshot, created_at
               FROM estate_property_versions WHERE property_id=%s
               ORDER BY version DESC""",
            (property_id,),
        ).fetchall()


def _evidence(row: dict, body: PropertySearch, filters: dict) -> dict:
    terms = sorted(set(re.findall(r"[a-z0-9]+", body.query.lower())))
    fields = {
        "title": row["title"], "description": row["description"],
        "city": row["city"], "locality": row["locality"],
        "amenities": " ".join(row["amenities"]),
    }
    matched_terms = sorted({
        term for term in terms
        if any(term in str(value).lower() for value in fields.values())
    })
    matched_fields = sorted({
        name for name, value in fields.items()
        if any(term in str(value).lower() for term in terms)
    })
    return {
        "property_version": row["current_version"],
        "source_uri": row["source_uri"],
        "matched_terms": matched_terms,
        "matched_fields": matched_fields,
        "applied_filters": filters,
    }


def search_properties(database, principal: Principal, body: PropertySearch,
                      run_id: str | None = None, embedding_service=None) -> dict:
    if body.strategy == "vector":
        if embedding_service is None:
            raise HTTPException(409, "Vector retrieval is not configured.")
        return embedding_service.search(principal, body, run_id=run_id)
    filters = body.model_dump(
        mode="json", exclude={"query", "strategy", "embedding_model_alias"},
        exclude_none=True,
    )
    clauses = [
        "p.organization_id=%s", "p.listing_status='active'",
        """(p.search_vector @@ websearch_to_tsquery('english', %s)
             OR similarity(lower(p.title || ' ' || p.locality || ' ' || p.city),
                           lower(%s)) > 0.05)""",
    ]
    parameters: list = [
        body.query, body.query, principal.organization_id, body.query, body.query,
    ]
    if body.city is not None:
        clauses.append("lower(p.city)=lower(%s)")
        parameters.append(body.city)
    if body.property_type is not None:
        clauses.append("p.property_type=%s")
        parameters.append(body.property_type)
    if body.min_bedrooms is not None:
        clauses.append("p.bedrooms >= %s")
        parameters.append(body.min_bedrooms)
    if body.max_price_inr is not None:
        clauses.append("p.price_inr <= %s")
        parameters.append(body.max_price_inr)
    if body.required_amenities:
        clauses.append("p.amenities @> %s::text[]")
        parameters.append(body.required_amenities)
    parameters.append(body.limit)
    with database.connect() as connection:
        if run_id is not None:
            # Serialize retries around the run so the search and its frozen results
            # survive a crash before the LangGraph checkpoint is written.
            run = connection.execute(
                """SELECT run_id FROM sentinel_runs
                   WHERE run_id=%s AND organization_id=%s FOR UPDATE""",
                (run_id, principal.organization_id),
            ).fetchone()
            if run is None:
                raise HTTPException(404, "Run not found.")
            existing = connection.execute(
                """SELECT query_text, filters, result_snapshot
                   FROM estate_retrieval_queries
                   WHERE run_id=%s AND organization_id=%s""",
                (run_id, principal.organization_id),
            ).fetchone()
            if existing is not None:
                if existing["query_text"] != body.query or existing["filters"] != filters:
                    raise HTTPException(409, "Run retrieval input has changed.")
                return existing["result_snapshot"]
        rows = connection.execute(
            f"""SELECT p.*,
                       (0.8 * ts_rank_cd(
                           p.search_vector, websearch_to_tsquery('english', %s)
                        ) + 0.2 * similarity(
                           lower(p.title || ' ' || p.locality || ' ' || p.city), lower(%s)
                        )) AS retrieval_score
                 FROM estate_properties p
                 WHERE {' AND '.join(clauses)}
                 ORDER BY retrieval_score DESC, p.updated_at DESC, p.property_id
                 LIMIT %s""",
            parameters,
        ).fetchall()
        results = []
        evidence_log = []
        for row in rows:
            evidence = _evidence(row, body, filters)
            score = round(float(row["retrieval_score"]), 6)
            result = {"property": property_view(row), "score": score, "evidence": evidence}
            results.append(result)
            evidence_log.append({
                "property_id": str(row["property_id"]), "score": score, **evidence,
            })
        retrieval_id = uuid4()
        response = PropertySearchResponse.model_validate({
            "retrieval_id": retrieval_id, "strategy": "hybrid_lexical_v1", "results": results,
        }).model_dump(mode="json")
        connection.execute(
            """INSERT INTO estate_retrieval_queries
               (retrieval_id, organization_id, query_text, filters, strategy,
                result_evidence, created_by_key_id, run_id, result_snapshot)
               VALUES (%s, %s, %s, %s, 'hybrid_lexical_v1', %s, %s, %s, %s)""",
            (retrieval_id, principal.organization_id, body.query, Jsonb(filters),
             Jsonb(evidence_log), principal.api_key_id, run_id,
             Jsonb(response) if run_id is not None else None),
        )
    return response


def get_retrieval(database, principal: Principal, retrieval_id: str) -> dict:
    with database.connect() as connection:
        row = connection.execute(
            """SELECT retrieval_id, query_text, filters, strategy, result_evidence,
                      embedding_model_alias, embedding_model_id, embedding_backend,
                      created_at
               FROM estate_retrieval_queries
               WHERE retrieval_id=%s AND organization_id=%s""",
            (retrieval_id, principal.organization_id),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Property retrieval not found.")
    return row
