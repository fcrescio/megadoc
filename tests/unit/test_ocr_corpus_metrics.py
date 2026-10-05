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


def test_int8_only_summary_does_not_invent_fp16_pairs():
    values = concordance("100 test", "100 test")
    row = {"document_id": "one", "dots_table_profile": {"tables": 0},
           "int8": {"status": "ok", "seconds": 1, "concordance": values,
                    "table_profile": {"tables": 0}}}
    result = summarize([row], 1, 1, "finished", variants=("int8",))
    assert set(result["variants"]) == {"int8"}
    assert "not_applicable" in result["paired"]
    assert result["strata"]["dots_no_table"]["pages"] == 1


def test_checkpoint_prevents_repeating_completed_requests(tmp_path):
    import json
    saved = {"status": "failed", "error": "previous failure", "seconds": 1}
    (tmp_path / "page-0001-fp16.json").write_text(json.dumps(saved))
    assert runner.recognize(None, "unused", b"", tmp_path, "fp16", 0, None, 8192, {}) == saved


def test_runtime_and_network_failures_stop_before_next_page():
    for record in ({"status": "failed", "http_status": 503, "error": "runtime"},
                   {"status": "failed", "error": "network"},
                   {"status": "failed", "http_status": 200, "error": "metadata mismatch"},
                   {"status": "failed", "http_status": 401, "error": "authentication"}):
        with pytest.raises(RuntimeError, match="Stopping"):
            runner.assert_backend_usable(None, "unused", record)


def test_isolated_page_error_continues_only_if_backend_is_healthy():
    import httpx
    record = {"status": "failed", "http_status": 502}
    for health in (200, 503):
        with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(health, json={}))) as client:
            if health == 200:
                runner.assert_backend_usable(client, "http://example/v1", record)
            else:
                with pytest.raises(httpx.HTTPStatusError):
                    runner.assert_backend_usable(client, "http://example/v1", record)
