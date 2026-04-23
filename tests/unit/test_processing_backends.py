from pathlib import Path

from common.config import Settings
from common.domain.models import OCRResultModel
from common.processing.backends import DoclingProcessingBackend


class StubDoclingBackend(DoclingProcessingBackend):
    def __init__(self, settings: Settings, tmp_path: Path) -> None:
        super().__init__(settings)
        self._warmup_lock_path = tmp_path / "docling-init.lock"
        self._warmup_ready_path = tmp_path / "docling-init.ready"
        self.convert_calls = 0

    def _convert(self, source: Path) -> OCRResultModel:
        self.convert_calls += 1
        return OCRResultModel(
            engine_name="docling",
            engine_version="test",
            pipeline_version="test",
            full_text="text",
            markdown_text="md",
            structured_json={"pages": []},
            page_count=1,
            confidence_summary=None,
        )


def test_docling_backend_marks_warmup_ready_after_first_success(tmp_path: Path) -> None:
    backend = StubDoclingBackend(Settings(), tmp_path)

    result = backend.process(tmp_path / "doc.pdf")

    assert result.engine_name == "docling"
    assert backend.convert_calls == 1
    assert backend._warmup_ready_path.exists()


def test_docling_backend_skips_lock_once_warmed(tmp_path: Path) -> None:
    backend = StubDoclingBackend(Settings(), tmp_path)
    backend._warmup_ready_path.touch()

    backend.process(tmp_path / "doc.pdf")
    backend.process(tmp_path / "doc.pdf")

    assert backend.convert_calls == 2
