from api.services.retrieval import RetrievalService


def test_rrf_merges_same_page_and_preserves_both_channels():
    service = RetrievalService(
        lexical_search=lambda query, limit: {
            "hits": [{
                "document_id": "doc-1", "page_number": 3, "snippet": "keyword",
                "original_filename": "one.pdf", "score": 4,
            }]
        },
        semantic_search=lambda query, limit: {
            "results": [{
                "source_type": "ocr_page", "source_id": "ocr-1", "document_id": "doc-1",
                "page_from": 3, "page_to": 3, "snippet": "semantic", "score": 0.9,
                "metadata": {"page_number": 3},
            }]
        },
    )

    result = service.retrieve("saldo", limit=5)

    assert len(result["results"]) == 1
    assert result["results"][0]["channels"] == ["lexical", "semantic"]
    assert result["results"][0]["ranks"] == {"lexical": 1, "semantic": 1}
    assert result["results"][0]["page_from"] == 3


def test_rrf_diversifies_documents():
    candidates = [
        {"source_type": "ocr_page", "document_id": "doc-1", "page_from": page, "page_to": page}
        for page in range(1, 5)
    ] + [{"source_type": "ocr_page", "document_id": "doc-2", "page_from": 1, "page_to": 1}]

    results = RetrievalService.fuse_ranked(
        {"lexical": candidates}, limit=4, max_per_document=2
    )

    assert [result["document_id"] for result in results] == ["doc-1", "doc-1", "doc-2"]


def test_semantic_failure_is_explicit_and_lexical_results_survive():
    def broken_semantic(query, limit):
        raise TimeoutError("embedding cold start")

    service = RetrievalService(
        lexical_search=lambda query, limit: {
            "hits": [{"document_id": "doc-1", "page_number": 2, "snippet": "Bonacci", "score": 1}]
        },
        semantic_search=broken_semantic,
    )

    result = service.retrieve("Bonacci", limit=3)

    assert len(result["results"]) == 1
    assert result["coverage"] == {"lexical": 1, "semantic": 0}
    assert result["warnings"] == ["semantic retrieval unavailable: TimeoutError: embedding cold start"]


def test_same_channel_does_not_score_same_page_twice():
    results = RetrievalService.fuse_ranked(
        {
            "semantic": [
                {
                    "source_type": "ocr_page", "source_id": "ocr-1",
                    "document_id": "doc-1", "page_from": 3, "page_to": 3,
                },
                {
                    "source_type": "specialist_result", "source_id": "specialist-1",
                    "document_id": "doc-1", "page_from": 3, "page_to": 3,
                },
            ]
        },
        limit=5,
    )

    assert len(results) == 1
    assert results[0]["channels"] == ["semantic"]
    assert results[0]["ranks"] == {"semantic": 1}
    assert results[0]["rrf_score"] == round(1 / 61, 8)
    assert {source["source_type"] for source in results[0]["evidence_sources"]} == {
        "ocr_page",
        "specialist_result",
    }
