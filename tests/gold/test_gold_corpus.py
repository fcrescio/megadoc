from pathlib import Path

from scripts.evaluate_gold_corpus import evaluate_manifest


def test_minimal_gold_corpus_passes():
    summary = evaluate_manifest(Path("tests/gold/manifest.json"))

    assert summary["failed"] == 0, summary
