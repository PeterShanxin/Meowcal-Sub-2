"""Reproduce the evidence index from anonymized authored native feature counts."""

import json
import math
from pathlib import Path


def fit(ledger: dict) -> dict:
    rows = ledger["rows"]
    settings = ledger["fit"]
    weights = [0.0] * 7
    count = sum(row["count"] for row in rows)
    for _ in range(settings["iterations"]):
        gradient = [0.0] * 7
        for row in rows:
            values = [1.0, *map(float, row["features"])]
            score = 1 / (1 + math.exp(-sum(a * b for a, b in zip(weights, values, strict=True))))
            for index, value in enumerate(values):
                gradient[index] += (score - row["label"]) * value * row["count"]
        for index in range(7):
            weights[index] -= settings["learningRate"] * (
                gradient[index] / count + (settings["ridge"] * weights[index] if index else 0)
            )
            # Progress features may add support; absence/repetition cannot.
            if index in (1, 2, 3):
                weights[index] = max(0.0, weights[index])
            elif index in (4, 5, 6):
                weights[index] = min(0.0, weights[index])

    def score(features):
        return 1 / (1 + math.exp(-sum(a * b for a, b in zip(weights, [1, *features], strict=True))))

    ambiguous = score((0, 0, 0, 0, 1, 1))
    text = score((0, 1, 0, 0, 1, 1))
    motion = score((1, 0, 0, 0, 1, 0))
    audio = score((0, 0, 1, 0, 1, 1))
    enter = (max(ambiguous, text) + min(motion, audio)) / 2
    return {
        "coefficients": weights,
        "ambiguous": ambiguous,
        "text": text,
        "motion": motion,
        "audio": audio,
        "enter": enter,
        "leave": (ambiguous + enter) / 2,
    }


if __name__ == "__main__":
    path = (
        Path(__file__).resolve().parents[1] / "tests/fixtures/playing-confidence-calibration.json"
    )
    print(json.dumps(fit(json.loads(path.read_text(encoding="utf-8"))), indent=2))
