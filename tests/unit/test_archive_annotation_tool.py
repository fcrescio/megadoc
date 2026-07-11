from pathlib import Path

from scripts.archive_annotation_server import (
    annotation_progress,
    empty_annotations,
    load_annotations,
    save_annotations,
)
from scripts.validate_archive_annotations import validate_annotations


def _case(case_id: str = "case-1", pages: int = 2):
    return {"case_id": case_id, "pages": pages}


def test_annotation_save_is_round_trip(tmp_path: Path):
    path = tmp_path / "annotations.json"
    payload = empty_annotations()
    payload["documents"] = {"case-1": {"reviewed": True}}

    save_annotations(path, payload)
    loaded = load_annotations(path)

    assert loaded["documents"]["case-1"]["reviewed"] is True
    assert loaded["updated_at"]
    assert not list(tmp_path.glob(".annotations.json.*"))


def test_progress_counts_review_and_specialists():
    payload = empty_annotations()
    payload["documents"] = {
        "case-1": {
            "reviewed": True,
            "document_units": [{"start_page": 1, "end_page": 2}],
            "specialist": {"kind": "payable"},
        }
    }
    payload["questions"] = [{"question": "Q"}]

    progress = annotation_progress([_case()], payload)

    assert progress["documents_reviewed"] == 1
    assert progress["document_units"] == 1
    assert progress["payable_cases"] == 1
    assert progress["questions"] == 1


def test_strict_validator_accepts_complete_fixture():
    cases = [_case(f"case-{index}", 2) for index in range(1, 21)]
    payload = empty_annotations()
    for index, case in enumerate(cases, start=1):
        kind = "payable" if index <= 10 else "accounting"
        specialist = (
            {"kind": kind, "issuer": "Issuer", "amount": "10", "due_date": "2026-01-01"}
            if kind == "payable"
            else {"kind": kind, "table_pages": "1-2", "cell_checks": "p.1 | total | 10"}
        )
        payload["documents"][case["case_id"]] = {
            "reviewed": True,
            "orientation_verified": True,
            "document_type": "fattura" if kind == "payable" else "rendiconto_contabile",
            "title": case["case_id"],
            "document_units": [{
                "start_page": 1, "end_page": 2,
                "document_type": "fattura" if kind == "payable" else "rendiconto_contabile",
                "title": case["case_id"],
            }],
            "specialist": specialist,
        }
    payload["questions"] = [
        {"question": f"Question {index}", "answerable": True,
         "expected_answer": "Answer", "evidence": "case-1:1"}
        for index in range(30)
    ]

    report = validate_annotations(cases, payload)

    assert report["valid"], report
