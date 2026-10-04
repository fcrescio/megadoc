import importlib.util
from pathlib import Path
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from ocr_corpus_metrics import canonical_text, concordance, summarize, table_profile

spec = importlib.util.spec_from_file_location("benchmark_ocr_corpus", SCRIPTS / "benchmark_ocr_corpus.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_canonicalization_removes_image_references_and_normalizes_markdown():
    assert canonical_text("# HELLO\n![Image 0](private/path.jpg)\n123,45") == "hello 123,45"
    assert concordance("**Hello**", "<b>hello</b>")["canonical_text_identical"]


def test_numeric_multisets_count_occurrences_not_unique_values():
    scores = concordance("123,45 123,45 2007", "123,45 2008")
    assert scores["shared_numeric_occurrences"] == 1
    assert scores["numeric_retention_not_accuracy"] == pytest.approx(1 / 3)
    assert not scores["numeric_multiset_identical"]
    assert concordance("text", "text")["numeric_retention_not_accuracy"] is None


def test_table_profile_counts_physical_cells_and_preserves_spans():
    page = {"tables": [{"cells": [{"html": "<table><tr><td colspan='2'>a</td></tr><tr><td>b</td><td>c</td></tr></table>"}]}]}
    assert table_profile(page) == {"tables": 1, "rows": 2, "physical_cells": 3}


def test_paired_summary_clusters_versions_and_pages_by_document():
    def row(document, delta):
        base = concordance("100 hello", "100 hello")
        changed = {**base, "word_sequence_agreement_not_accuracy": 1 + delta}
        return {"document_id": document, "dots_table_profile": {"tables": 0},
                "fp16": {"status": "ok", "seconds": 10, "concordance": base, "table_profile": {"tables": 0}},
                "int8": {"status": "ok", "seconds": 8, "concordance": changed, "table_profile": {"tables": 0}},
                "fp16_int8": base}
    rows = [row("same-document", -0.2)] * 10 + [row("other-document", 0)]
    rows.append({"document_id": "failed", "dots_table_profile": {"tables": 0},
                 "fp16": {"status": "failed"}, "int8": {"status": "failed"}})
    result = summarize(rows, 12, 3, "running")
    assert result["variants"]["fp16"]["failed"] == 1
    assert result["paired"]["successful_page_pairs"] == 11
    assert result["paired"]["distinct_documents_observed"] == 2
    delta = result["paired"]["word_sequence_agreement_not_accuracy_int8_minus_fp16"]
    assert delta["document_means"]["mean"] == pytest.approx(-0.1)
    assert delta["document_means"]["n"] == 2
    assert delta["document_bootstrap_95_ci"] is not None


def test_missing_or_misnumbered_baseline_page_is_not_silently_compared():
    baseline = {"structured_json": {"pages": [{"page_number": 2}]}}
    assert runner.baseline_page(baseline, 0) is None
    assert runner.baseline_page(baseline, 1) is None


def test_checkpoint_prevents_repeating_completed_requests(tmp_path):
    import json
    saved = {"status": "failed", "error": "previous failure", "seconds": 1}
    (tmp_path / "page-0001-fp16.json").write_text(json.dumps(saved))
    assert runner.recognize(None, "unused", b"", tmp_path, "fp16", 0, None, 8192, {}) == saved
