import math
import unittest

from fastapi import HTTPException

from sentinel.embeddings import (
    EmbeddingService, cosine_similarity, validate_embedding, vector_literal,
)
from sentinel.schemas import PropertyEmbeddingBackfill, PropertySearch
from sentinel.security import Principal


class EmbeddingContractTests(unittest.TestCase):
    def test_rejects_wrong_size_nonfinite_and_zero_vectors(self):
        for values in (
            [1.0], [0.0] * 512, [math.nan] + [0.0] * 511,
            [math.inf] + [0.0] * 511,
        ):
            with self.subTest(first=values[0], size=len(values)):
                with self.assertRaises(ValueError):
                    validate_embedding(values)

    def test_exact_cosine_ranking_and_pgvector_literal(self):
        left = validate_embedding([1.0] + [0.0] * 511)
        same = validate_embedding([2.0] + [0.0] * 511)
        other = validate_embedding([0.0, 1.0] + [0.0] * 510)
        self.assertAlmostEqual(cosine_similarity(left, same), 1.0)
        self.assertAlmostEqual(cosine_similarity(left, other), 0.0)
        self.assertEqual(vector_literal(left).count(','), 511)

    def test_backfill_and_search_enforce_roles_before_provider_access(self):
        service = EmbeddingService(None, None)
        developer = Principal("key", "organization", "developer")
        reviewer = Principal("key", "organization", "reviewer")
        with self.assertRaises(HTTPException) as denied_backfill:
            service.backfill(developer, PropertyEmbeddingBackfill())
        self.assertEqual(denied_backfill.exception.status_code, 403)
        with self.assertRaises(HTTPException) as denied_search:
            service.search(reviewer, PropertySearch(query="pool", strategy="vector"))
        self.assertEqual(denied_search.exception.status_code, 403)


if __name__ == '__main__':
    unittest.main()
