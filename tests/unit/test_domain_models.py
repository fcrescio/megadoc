from common.domain.models import OCRResultModel


def test_ocr_result_model_serialization() -> None:
    result = OCRResultModel(
        engine_name="fake",
        engine_version="1",
        pipeline_version="v1",
        full_text="text",
        markdown_text="# text",
        structured_json={"pages": []},
        page_count=1,
        confidence_summary={"avg": 1.0},
    )
    payload = result.model_dump()
    assert payload["engine_name"] == "fake"
    assert payload["page_count"] == 1

