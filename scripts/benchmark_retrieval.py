"""Repeatable retrieval benchmark; --vector explicitly opts into paid embedding calls."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import dev
import native_postgres
from sentinel.database import Database
from sentinel.embeddings import EmbeddingService
from sentinel.properties import search_properties, upsert_property_batch
from sentinel.provider_registry import CredentialCipher
from sentinel.schemas import PropertyEmbeddingBackfill, PropertySearch, PropertyUpsert
from sentinel.security import Principal, digest_key


def local_principal(database, token: str, pepper: str) -> Principal:
    prefix = "_".join(token.split("_", 2)[:2])
    with database.connect() as connection:
        row = connection.execute(
            """SELECT api_key_id, organization_id, role FROM sentinel_api_keys
               WHERE key_prefix=%s AND key_digest=%s""",
            (prefix, digest_key(token, pepper)),
        ).fetchone()
    if row is None:
        raise RuntimeError("Configured local API key was not found.")
    return Principal(str(row["api_key_id"]), str(row["organization_id"]), row["role"])


def percentile(values: list[float], proportion: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, math.ceil(len(ordered) * proportion) - 1)]


def evaluate(dataset: dict, database, principal: Principal,
             strategy: str, embedding_service=None, model_alias: str = "estate_embeddings") -> dict:
    latencies = []
    recalls = []
    reciprocals = []
    actual_strategy = None
    for case in dataset["queries"]:
        body = PropertySearch.model_validate({
            "query": case["query"], "city": dataset["city"], "limit": 3,
            "strategy": strategy, "embedding_model_alias": model_alias,
            **case["filters"],
        })
        started = monotonic()
        response = search_properties(
            database, principal, body, embedding_service=embedding_service
        )
        latencies.append((monotonic() - started) * 1000)
        actual_strategy = response["strategy"]
        keys = [item["property"]["external_key"] for item in response["results"]]
        relevant = set(case["relevant"])
        recalls.append(len(relevant.intersection(keys)) / len(relevant))
        ranks = [1 / (index + 1) for index, key in enumerate(keys) if key in relevant]
        reciprocals.append(max(ranks, default=0))
    return {
        "strategy": actual_strategy, "queries": len(dataset["queries"]),
        "recall_at_3": round(statistics.mean(recalls), 4),
        "mrr_at_3": round(statistics.mean(reciprocals), 4),
        "p50_ms": round(statistics.median(latencies), 2),
        "p95_ms": round(percentile(latencies, .95), 2),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vector", action="store_true",
                        help="Backfill and query the configured paid embedding model.")
    parser.add_argument("--model-alias", default="estate_embeddings")
    args = parser.parse_args()
    dev.setup()
    config = dev.load_config()
    database = Database(native_postgres.dsn())
    principal = local_principal(
        database, config["keys"]["developer"], config["auth_pepper"]
    )
    raw = (ROOT / "datasets" / "retrieval-v1.json").read_bytes()
    dataset = json.loads(raw)
    properties = [PropertyUpsert.model_validate(item) for item in dataset["properties"]]
    upsert_property_batch(database, principal, properties)
    report = {
        "dataset_version": dataset["version"],
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "corpus_size": len(properties),
        "labels": "synthetic fixture; not outside-pilot relevance judgments",
        "lexical": evaluate(dataset, database, principal, "lexical"),
        "vector": None,
    }
    if args.vector:
        service = EmbeddingService(
            database, CredentialCipher(config["credential_encryption_key"])
        )
        admin = local_principal(
            database, config["keys"]["admin"], config["auth_pepper"]
        )
        backfill = PropertyEmbeddingBackfill(
            model_alias=args.model_alias, external_key_prefix="bench-v1-"
        )
        while True:
            outcome = service.backfill(admin, backfill)
            if outcome["remaining"] == 0:
                break
            if outcome["embedded"] == 0:
                raise RuntimeError("Embedding backfill made no progress.")
        report["vector"] = evaluate(
            dataset, database, principal, "vector", service, args.model_alias
        )
    destination = ROOT / ".local" / "retrieval-benchmark.json"
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Lexical Recall@3: {report['lexical']['recall_at_3']}")
    if report["vector"]:
        print(f"Vector Recall@3: {report['vector']['recall_at_3']}")
    else:
        print("Vector benchmark skipped; pass --vector after configuring a model key.")
    print(f"Report: {destination}")


if __name__ == "__main__":
    main()
