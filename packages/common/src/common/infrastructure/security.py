import hashlib
from pathlib import Path

from common.domain.exceptions import ValidationError

PDF_MAGIC = b"%PDF-"


def validate_pdf_magic_bytes(path: Path) -> None:
    with path.open("rb") as handle:
        magic = handle.read(len(PDF_MAGIC))
    if magic != PDF_MAGIC:
        raise ValidationError("Uploaded file is not a valid PDF.")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()

