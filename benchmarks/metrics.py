"""Dependency-free statistical functions used by the benchmark reports."""
from __future__ import annotations

import math
import statistics
from collections import Counter
from typing import Iterable, Sequence


def percentile(values: Sequence[float], proportion: float) -> float:
    if not values:
        raise ValueError("A percentile needs at least one sample.")
    if not 0 < proportion <= 1:
        raise ValueError("Percentile proportion must be in (0, 1].")
    ordered = sorted(float(value) for value in values)
    return ordered[min(len(ordered) - 1, math.ceil(len(ordered) * proportion) - 1)]


def distribution(values: Sequence[float]) -> dict[str, float | int]:
    if not values:
        raise ValueError("A distribution needs at least one sample.")
    samples = [float(value) for value in values]
    return {
        "samples": len(samples),
        "mean": round(statistics.fmean(samples), 6),
        "p50": round(percentile(samples, 0.50), 6),
        "p95": round(percentile(samples, 0.95), 6),
        "p99": round(percentile(samples, 0.99), 6),
        "min": round(min(samples), 6),
        "max": round(max(samples), 6),
    }


def _ratio(numerator: int | float, denominator: int | float) -> float:
    return float(numerator / denominator) if denominator else 0.0


def classification_metrics(expected: Sequence[str], predicted: Sequence[str],
                           labels: Iterable[str]) -> dict[str, object]:
    if not expected or len(expected) != len(predicted):
        raise ValueError("Expected and predicted labels must be non-empty and aligned.")
    ordered_labels = list(labels)
    if len(set(ordered_labels)) != len(ordered_labels):
        raise ValueError("Classification labels must be unique.")
    known = set(ordered_labels)
    if set(expected) - known or set(predicted) - known:
        raise ValueError("Classification values must use declared labels.")

    matrix = {actual: {guess: 0 for guess in ordered_labels} for actual in ordered_labels}
    for actual, guess in zip(expected, predicted):
        matrix[actual][guess] += 1

    per_category: dict[str, dict[str, float | int]] = {}
    total = len(expected)
    for label in ordered_labels:
        tp = matrix[label][label]
        fp = sum(matrix[actual][label] for actual in ordered_labels if actual != label)
        fn = sum(matrix[label][guess] for guess in ordered_labels if guess != label)
        tn = total - tp - fp - fn
        precision = _ratio(tp, tp + fp)
        recall = _ratio(tp, tp + fn)
        f1 = _ratio(2 * precision * recall, precision + recall)
        per_category[label] = {
            "support": sum(matrix[label].values()), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "precision": round(precision, 6), "recall": round(recall, 6), "f1": round(f1, 6),
        }

    supports = Counter(expected)
    macro = {name: statistics.fmean(float(per_category[label][name]) for label in ordered_labels)
             for name in ("precision", "recall", "f1")}
    weighted = {name: sum(float(per_category[label][name]) * supports[label]
                          for label in ordered_labels) / total
                for name in ("precision", "recall", "f1")}
    correct = sum(actual == guess for actual, guess in zip(expected, predicted))
    accuracy = correct / total
    return {
        "samples": total, "correct": correct, "accuracy": round(accuracy, 6),
        "precision_macro": round(macro["precision"], 6),
        "recall_macro": round(macro["recall"], 6), "f1_macro": round(macro["f1"], 6),
        "precision_micro": round(accuracy, 6), "recall_micro": round(accuracy, 6),
        "f1_micro": round(accuracy, 6),
        "precision_weighted": round(weighted["precision"], 6),
        "recall_weighted": round(weighted["recall"], 6),
        "f1_weighted": round(weighted["f1"], 6),
        "labels": ordered_labels, "confusion_matrix": matrix, "per_category": per_category,
    }


def percent_change(before: float, after: float) -> float | None:
    if before == 0:
        return None
    return round(((after - before) / before) * 100, 6)
