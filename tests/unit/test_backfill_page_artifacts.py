from scripts.backfill_page_artifacts import _has_materialized_page_artifacts


def test_has_materialized_page_artifacts_requires_non_empty_list():
    assert _has_materialized_page_artifacts({"page_artifacts": [{"page_number": 1}]})
    assert not _has_materialized_page_artifacts({"page_artifacts": []})
    assert not _has_materialized_page_artifacts({"page_artifacts": None})
    assert not _has_materialized_page_artifacts({})
    assert not _has_materialized_page_artifacts(None)
