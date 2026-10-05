import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from triage_ocr_qwen import numeric_diff, select_pages, transcription_text
from ocr_corpus_metrics import concordance


def row(case, document, page, word=.9, numeric=1, count=20, words=150):
    return {"ocr_result_id": case, "document_id": document, "page": page,
            "int8": {"status": "ok", "concordance": {
                "word_sequence_agreement_not_accuracy": word,
                "numeric_retention_not_accuracy": numeric,
                "reference_numeric_occurrences": count, "reference_words": words}}}


def test_all_failures_selected_and_overlapping_reasons_deduplicated():
    failed = {"ocr_result_id": "failed", "document_id": "one", "page": 1,
              "int8": {"status": "failed"}}
    selected = select_pages([failed, row("weak", "two", 1, word=.1, numeric=.1)], 1)
    assert len(selected) == 2
    assert selected[0]["reasons"] == ["glm_failed"]
    assert selected[1]["reasons"] == ["low_word_agreement", "low_numeric_retention"]


def test_rankings_preserve_document_diversity_and_reject_tiny_controls():
    rows = [row("one", "same", 1, word=.01, numeric=.1),
            row("one", "same", 2, word=.02, numeric=.2),
            row("two", "other", 1, word=.03, numeric=.3),
            row("tiny", "tiny", 1, word=1, words=2),
            row("control", "control", 1, word=1)]
    selected = select_pages(rows, 2)
    assert ("one", 2) not in [(r["ocr_result_id"], r["page"]) for r in selected]
    assert [r["ocr_result_id"] for r in selected if "high_agreement_control" in r["reasons"]] == ["control"]


def test_numeric_difference_keeps_repeated_occurrences():
    assert numeric_diff("123,45 123,45", "123,45 2007") == {
        "reference_only": ["123,45"], "candidate_only": ["2007"]}


def test_html_wrapper_does_not_turn_css_attributes_into_ocr_numbers():
    raw = '```html\n<table style="width:100%;font-size:10px"><tr><td>123,45</td></tr></table>\n```'
    text = transcription_text(raw)
    assert concordance("123,45", text)["numeric_multiset_identical"]
    assert transcription_text("ordinary text") == "ordinary text"
