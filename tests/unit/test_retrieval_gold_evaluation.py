from scripts.evaluate_retrieval_gold import _matches_evidence, parse_evidence, percentile


def test_parse_evidence_supports_ranges_and_multiple_sources():
    assert parse_evidence("case-a:3, case-b:8-6\ncase-c:10") == [
        ("case-a", 3, 3),
        ("case-b", 6, 8),
        ("case-c", 10, 10),
    ]


def test_page_range_result_matches_any_gold_page():
    expected = {("doc-a", 5), ("doc-a", 6)}

    assert _matches_evidence(
        {"document_id": "doc-a", "page_from": 4, "page_to": 5}, expected
    )
    assert not _matches_evidence(
        {"document_id": "doc-b", "page_from": 5, "page_to": 6}, expected
    )


def test_percentile_uses_nearest_rank():
    assert percentile([0.1, 0.2, 0.3, 0.4], 0.95) == 0.4
    assert percentile([], 0.95) is None
