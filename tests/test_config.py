import os
import unittest
from unittest.mock import patch

from sentinel.config import Settings


class SettingsTests(unittest.TestCase):
    def environment(self, **values):
        return patch.dict(
            os.environ,
            {
                "SENTINEL_DATABASE_URL": "postgresql://sentinel.test/database",
                "SENTINEL_AUTH_PEPPER": "test-pepper",
                "SENTINEL_CREDENTIAL_ENCRYPTION_KEY":
                    "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
                **values,
            },
            clear=True,
        )

    def test_execution_lease_defaults_to_thirty_seconds(self):
        with self.environment():
            settings = Settings.from_environment()
        self.assertEqual(settings.execution_lease_seconds, 30)

    def test_execution_lease_must_be_within_safe_bounds(self):
        for value in ("not-a-number", "2", "3601"):
            with self.subTest(value=value), self.environment(
                SENTINEL_EXECUTION_LEASE_SECONDS=value
            ):
                with self.assertRaises(RuntimeError):
                    Settings.from_environment()

    def test_model_timeout_must_be_within_safe_bounds(self):
        for value in ("not-a-number", "0", "121"):
            with self.subTest(value=value), self.environment(
                SENTINEL_MODEL_TIMEOUT_SECONDS=value
            ):
                with self.assertRaises(RuntimeError):
                    Settings.from_environment()

    def test_request_limits_reject_invalid_environment_values(self):
        for value in ("0", "100001", "not-an-integer"):
            with self.environment(SENTINEL_REQUESTS_PER_WINDOW=value):
                with self.assertRaises(RuntimeError):
                    Settings.from_environment()
        with self.environment(SENTINEL_REQUESTS_PER_WINDOW="5", SENTINEL_REQUEST_WINDOW_SECONDS="30"):
            settings = Settings.from_environment()
        self.assertEqual((settings.requests_per_window, settings.request_window_seconds), (5, 30))


if __name__ == "__main__":
    unittest.main()
