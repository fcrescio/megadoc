import importlib.util
from pathlib import Path

import fitz
import pytest


spec = importlib.util.spec_from_file_location("compare_archived_ocr", Path(__file__).resolve().parents[2] / "scripts/compare_archived_ocr.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def test_numeric_concordance_counts_duplicates_and_is_not_accuracy():
    result = benchmark.comparison("<table><tr><td>123,45</td></tr></table> 123,45 2007", "123,45 2008")
    assert result["shared_numeric_occurrences"] == 1
    assert result["baseline_numbers_absent"] == ["123,45", "2007"]
    assert result["candidate_numbers_added"] == ["2008"]


def test_replays_orientation_and_reverse_order(tmp_path):
    original = tmp_path / "original.pdf"
    normalized = tmp_path / "normalized.pdf"
    with fitz.open() as document:
        document.new_page().insert_text((50, 50), "first")
        document.new_page().insert_text((50, 50), "second")
        document.save(original)
    baseline = {
        "confidence_summary": {"orientation_preprocess": {"applied": True, "rotation_applied": 180, "page_order_reversed": True}},
        "structured_json": {"pages": [{"metadata": {}}, {"metadata": {"render_rotation": 90}}]},
    }
    mapping = benchmark.normalized_pdf(original, normalized, baseline)
    with fitz.open(normalized) as document:
        assert "second" in document[0].get_text()
        assert document[0].rotation == 180
        assert document[1].rotation == 270
    assert mapping[0]["original_page"] == 2
    with fitz.open(original) as document:
        assert document[0].rotation == 0


def test_does_not_apply_unaccepted_orientation(tmp_path):
    source, target = tmp_path / "original.pdf", tmp_path / "normalized.pdf"
    with fitz.open() as document:
        document.new_page()
        document.save(source)
    baseline = {"confidence_summary": {"orientation_preprocess": {"applied": False, "rotation_applied": 180}}, "structured_json": {"pages": []}}
    mapping = benchmark.normalized_pdf(source, target, baseline)
    assert mapping[0]["rotation"] == 0


def test_explicit_rotation_override_is_a_separate_experiment(tmp_path):
    source, target = tmp_path / "original.pdf", tmp_path / "normalized.pdf"
    with fitz.open() as document:
        document.new_page()
        document.save(source)
    baseline = {"confidence_summary": {}, "structured_json": {"pages": []}}
    mapping = benchmark.normalized_pdf(source, target, baseline, [270])
    assert mapping[0]["rotation"] == 270
    with pytest.raises(ValueError, match="every source page"):
        benchmark.normalized_pdf(source, tmp_path / "invalid.pdf", baseline, [90, 180])
