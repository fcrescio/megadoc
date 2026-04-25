from pathlib import Path
from types import SimpleNamespace

from common.config import Settings
from common.processing.dots_native import DotsNativeOCRService


class StubDotsNativeOCRService(DotsNativeOCRService):
    def _render_page_candidate(self, source: Path, page_number: int, *, scale: float, rotation: int):
        return {
            "data_url": f"data:image/png;base64,page-{page_number}",
            "scale": scale,
            "rotation": rotation,
            "stats": {"mean_luma": 220.0, "dark_220_ratio": 0.10},
        }

    def _request(self, payload: dict[str, object]):
        prompt = payload["messages"][0]["content"][1]["text"]  # type: ignore[index]
        if "layout information" in prompt:
            return {
                "content": (
                    '[{"bbox":[0,0,100,20],"category":"Section-header","text":"## Heading"},'
                    '{"bbox":[0,21,100,60],"category":"Text","text":"Paragraph body"}]'
                ),
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            }
        return {
            "content": "fallback ocr text",
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        }


class FallbackDotsNativeOCRService(DotsNativeOCRService):
    def _render_page_candidate(self, source: Path, page_number: int, *, scale: float, rotation: int):
        return {
            "data_url": f"data:image/png;base64,page-{page_number}",
            "scale": scale,
            "rotation": rotation,
            "stats": {"mean_luma": 220.0, "dark_220_ratio": 0.10},
        }

    def _request(self, payload: dict[str, object]):
        prompt = payload["messages"][0]["content"][1]["text"]  # type: ignore[index]
        if "layout information" in prompt:
            return {
                "content": '[{"bbox":[0,0,100,100],"category":"Picture"}]',
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }
        return {
            "content": "fallback ocr text",
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        }


class RotationFallbackDotsNativeOCRService(DotsNativeOCRService):
    def _render_page_candidate(self, source: Path, page_number: int, *, scale: float, rotation: int):
        return {
            "data_url": f"data:image/png;base64:page-{page_number}-rot-{rotation}",
            "scale": scale,
            "rotation": rotation,
            "stats": {"mean_luma": 220.0, "dark_220_ratio": 0.10},
        }

    def _request(self, payload: dict[str, object]):
        prompt = payload["messages"][0]["content"][1]["text"]  # type: ignore[index]
        image_data_url = payload["messages"][0]["content"][0]["image_url"]["url"]  # type: ignore[index]
        if "rot-180" not in image_data_url:
            return None
        if "layout information" in prompt:
            return {
                "content": (
                    '[{"bbox":[0,0,100,20],"category":"Section-header","text":"## Rotated"},'
                    '{"bbox":[0,21,100,60],"category":"Text","text":"Recovered text"}]'
                ),
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            }
        return None


class SparsePageDotsNativeOCRService(DotsNativeOCRService):
    def _render_page_candidate(self, source: Path, page_number: int, *, scale: float, rotation: int):
        return {
            "data_url": f"data:image/png;base64:page-{page_number}-rot-{rotation}",
            "scale": scale,
            "rotation": rotation,
            "stats": {"mean_luma": 246.0, "dark_220_ratio": 0.01},
        }

    def _request(self, payload: dict[str, object]):
        return None


def test_dots_native_service_builds_layout_result(monkeypatch, tmp_path: Path) -> None:
    fake_document = SimpleNamespace(page_count=1, close=lambda: None)
    fake_fitz = SimpleNamespace(open=lambda source: fake_document)
    monkeypatch.setitem(__import__("sys").modules, "fitz", fake_fitz)

    service = StubDotsNativeOCRService(Settings())
    result = service.process(tmp_path / "doc.pdf")

    assert result.engine_name == "dots_native"
    assert result.page_count == 1
    assert result.structured_json["pages"][0]["metadata"]["mode"] == "layout"
    assert result.structured_json["pages"][0]["blocks"][0]["type"] == "heading"
    assert "Paragraph body" in result.full_text


def test_dots_native_service_falls_back_to_ocr(monkeypatch, tmp_path: Path) -> None:
    fake_document = SimpleNamespace(page_count=1, close=lambda: None)
    fake_fitz = SimpleNamespace(open=lambda source: fake_document)
    monkeypatch.setitem(__import__("sys").modules, "fitz", fake_fitz)

    service = FallbackDotsNativeOCRService(Settings())
    result = service.process(tmp_path / "doc.pdf")

    assert result.structured_json["pages"][0]["metadata"]["mode"] == "ocr"
    assert result.full_text == "fallback ocr text"
    assert result.confidence_summary["dots_native"]["fallback_to_ocr_pages"] == [1]


def test_dots_native_service_recovers_with_rotated_render(monkeypatch, tmp_path: Path) -> None:
    fake_document = SimpleNamespace(page_count=1, close=lambda: None)
    fake_fitz = SimpleNamespace(open=lambda source: fake_document)
    monkeypatch.setitem(__import__("sys").modules, "fitz", fake_fitz)

    service = RotationFallbackDotsNativeOCRService(Settings())
    result = service.process(tmp_path / "doc.pdf")

    page = result.structured_json["pages"][0]
    assert page["metadata"]["mode"] == "layout"
    assert page["metadata"]["render_rotation"] == 180
    assert "Recovered text" in result.full_text


def test_dots_native_service_marks_sparse_page_empty(monkeypatch, tmp_path: Path) -> None:
    fake_document = SimpleNamespace(page_count=1, close=lambda: None)
    fake_fitz = SimpleNamespace(open=lambda source: fake_document)
    monkeypatch.setitem(__import__("sys").modules, "fitz", fake_fitz)

    service = SparsePageDotsNativeOCRService(Settings())
    result = service.process(tmp_path / "doc.pdf")

    page = result.structured_json["pages"][0]
    assert page["metadata"]["mode"] == "empty"
    assert page["blocks"] == []
    assert result.confidence_summary["dots_native"]["empty_pages"] == [1]
