from common.config import Settings
from common.processing.preflight import PDFPreflightService


def test_preflight_reports_valid_sample_pdf(valid_pdf_path) -> None:
    fixture = valid_pdf_path

    report = PDFPreflightService(Settings()).analyze(fixture)

    assert report.valid_pdf is True
    assert report.page_count == 1
    assert report.bytes_per_page == fixture.stat().st_size
    assert report.text_extractable is False
    assert "image_only_likely" in report.flags
    assert "malformed_pdf" not in report.flags


def test_preflight_rejects_malformed_pdf(tmp_path) -> None:
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n")

    report = PDFPreflightService(Settings()).analyze(broken)

    assert report.valid_pdf is False
    assert "malformed_pdf" in report.flags
    assert report.error is not None
