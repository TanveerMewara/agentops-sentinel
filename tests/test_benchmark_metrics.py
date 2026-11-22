import unittest

from benchmarks.metrics import classification_metrics, distribution, percent_change, percentile


class BenchmarkMetricTests(unittest.TestCase):
    def test_nearest_rank_percentiles_keep_tail_samples(self):
        values = list(range(1, 101))
        self.assertEqual(percentile(values, .50), 50)
        self.assertEqual(percentile(values, .95), 95)
        self.assertEqual(percentile(values, .99), 99)
        self.assertEqual(distribution(values)["samples"], 100)

    def test_known_confusion_matrix_produces_expected_metrics(self):
        result = classification_metrics(
            ["ok", "ok", "failed", "failed"], ["ok", "failed", "failed", "failed"],
            ["ok", "failed"])
        self.assertEqual(result["accuracy"], .75)
        self.assertEqual(result["confusion_matrix"]["ok"]["failed"], 1)
        self.assertEqual(result["per_category"]["ok"]["recall"], .5)
        self.assertEqual(result["per_category"]["failed"]["precision"], round(2 / 3, 6))

    def test_invalid_samples_and_zero_baseline_fail_safely(self):
        with self.assertRaises(ValueError):
            percentile([], .95)
        with self.assertRaises(ValueError):
            classification_metrics(["ok"], [], ["ok"])
        self.assertIsNone(percent_change(0, 1))
