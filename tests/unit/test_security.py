from pathlib import Path

from common.infrastructure.security import sha256_file, validate_pdf_magic_bytes


def test_sha256_file(tmp_path: Path) -> None:
    sample = tmp_path / "sample.txt"
    sample.write_text("hello", encoding="utf-8")
    assert sha256_file(sample) == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


def test_validate_pdf_magic_bytes(tmp_path: Path) -> None:
    sample = tmp_path / "sample.pdf"
    sample.write_bytes(b"%PDF-1.4")
    validate_pdf_magic_bytes(sample)

