import unittest

from pydantic import ValidationError

from sentinel.properties import property_hash, property_snapshot
from sentinel.schemas import PropertyBatchUpsert, PropertyUpsert


def property_body(**changes):
    body = {
        "external_key": "listing-1",
        "title": "Three bedroom apartment",
        "description": "Bright apartment near the metro.",
        "city": "Gurugram",
        "locality": "Golf Course Road",
        "property_type": "apartment",
        "bedrooms": 3,
        "bathrooms": "2.5",
        "price_inr": "25000000.00",
        "area_sqft": "1800.00",
        "amenities": ["Pool", "Gym"],
        "source_uri": "https://estateflow.example/listings/1",
    }
    body.update(changes)
    return PropertyUpsert.model_validate(body)


class PropertyContractTests(unittest.TestCase):
    def test_snapshot_hash_is_stable_after_amenity_normalization(self):
        first = property_body(amenities=["Pool", "Gym"])
        second = property_body(amenities=["gym", "pool"])
        self.assertEqual(property_snapshot(first), property_snapshot(second))
        self.assertEqual(
            property_hash(property_snapshot(first)), property_hash(property_snapshot(second))
        )

    def test_duplicate_amenities_are_rejected(self):
        with self.assertRaises(ValidationError):
            property_body(amenities=["Pool", "pool"])

    def test_batch_rejects_duplicate_external_keys(self):
        with self.assertRaises(ValidationError):
            PropertyBatchUpsert(properties=[property_body(), property_body()])

    def test_source_link_cannot_execute_browser_code_or_embed_credentials(self):
        for source_uri in (
            "javascript:alert(1)", "https://operator:secret@estateflow.example/1",
        ):
            with self.subTest(source_uri=source_uri), self.assertRaises(ValidationError):
                property_body(source_uri=source_uri)


if __name__ == "__main__":
    unittest.main()
