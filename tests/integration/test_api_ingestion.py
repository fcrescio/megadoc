from pathlib import Path
from uuid import UUID

from common.application.services import OCRService


def test_upload_and_retrieve_document(client, tmp_path: Path) -> None:
    fixture = Path("tests/fixtures/sample.pdf")
    with fixture.open("rb") as handle:
        response = client.post("/documents/upload?auto_submit=false", files={"file": ("sample.pdf", handle, "application/pdf")})
    assert response.status_code == 200
    payload = response.json()
    document_id = payload["document_id"]

    document_response = client.get(f"/documents/{document_id}")
    assert document_response.status_code == 200
    assert document_response.json()["original_filename"] == "sample.pdf"


def test_process_job_persists_ocr_and_assets(client, db_session) -> None:
    fixture = Path("tests/fixtures/sample.pdf")
    with fixture.open("rb") as handle:
        response = client.post("/documents/upload?auto_submit=false", files={"file": ("sample.pdf", handle, "application/pdf")})

    assert response.status_code == 200
    payload = response.json()
    document_id = payload["document_id"]

    job_response = client.post("/jobs/ingest", json={"document_id": document_id, "priority": 5})
    assert job_response.status_code == 200
    job_id = job_response.json()["id"]

    result = OCRService(db_session).process_job(UUID(job_id))
    assert str(result.document_id) == document_id

    ocr_response = client.get(f"/documents/{document_id}/ocr")
    assert ocr_response.status_code == 200
    assert ocr_response.json()["engine_name"] == "fake"

    assets_response = client.get(f"/documents/{document_id}/assets")
    assert assets_response.status_code == 200
    assets = assets_response.json()
    asset_types = {asset["asset_type"] for asset in assets}
    assert {"original_pdf", "markdown", "text", "ocr_json"}.issubset(asset_types)

    markdown_asset = next(asset for asset in assets if asset["asset_type"] == "markdown")
    download_response = client.get(f"/documents/{document_id}/assets/{markdown_asset['id']}/download")
    assert download_response.status_code == 200
    assert download_response.headers["content-type"].startswith("text/markdown")
    assert b"# OCR Result" in download_response.content


def test_create_job_and_fetch_status(client) -> None:
    fixture = Path("tests/fixtures/sample.pdf")
    with fixture.open("rb") as handle:
        upload_response = client.post("/documents/upload?auto_submit=false", files={"file": ("sample.pdf", handle, "application/pdf")})
    document_id = upload_response.json()["document_id"]

    job_response = client.post("/jobs/ingest", json={"document_id": document_id, "priority": 3})
    assert job_response.status_code == 200
    job_id = job_response.json()["id"]

    status_response = client.get(f"/jobs/{job_id}")
    assert status_response.status_code == 200
    assert status_response.json()["document_id"] == document_id


def test_download_original_and_list_versions(client) -> None:
    fixture = Path("tests/fixtures/sample.pdf")
    with fixture.open("rb") as handle:
        response = client.post("/documents/upload?auto_submit=false", files={"file": ("sample.pdf", handle, "application/pdf")})

    assert response.status_code == 200
    payload = response.json()
    document_id = payload["document_id"]
    version_id = payload["version_id"]

    versions_response = client.get(f"/documents/{document_id}/versions")
    assert versions_response.status_code == 200
    versions = versions_response.json()
    assert len(versions) == 1
    assert versions[0]["id"] == version_id

    download_response = client.get(f"/documents/{document_id}/download")
    assert download_response.status_code == 200
    assert download_response.headers["content-type"].startswith("application/pdf")
    assert download_response.content.startswith(b"%PDF-")


def test_upload_same_external_id_creates_new_version(client, tmp_path: Path) -> None:
    first = tmp_path / "v1.pdf"
    second = tmp_path / "v2.pdf"
    first.write_bytes(b"%PDF-1.4\n% version one\n")
    second.write_bytes(b"%PDF-1.4\n% version two\n")

    with first.open("rb") as handle:
        response_one = client.post(
            "/documents/upload?auto_submit=false",
            data={"external_id": "contract-001"},
            files={"file": ("v1.pdf", handle, "application/pdf")},
        )
    with second.open("rb") as handle:
        response_two = client.post(
            "/documents/upload?auto_submit=false",
            data={"external_id": "contract-001"},
            files={"file": ("v2.pdf", handle, "application/pdf")},
        )

    assert response_one.status_code == 200
    assert response_two.status_code == 200

    payload_one = response_one.json()
    payload_two = response_two.json()
    assert payload_one["document_id"] == payload_two["document_id"]
    assert payload_one["version_id"] != payload_two["version_id"]
    assert payload_two["deduplicated"] is False

    versions_response = client.get(f"/documents/{payload_one['document_id']}/versions")
    assert versions_response.status_code == 200
    versions = versions_response.json()
    assert [version["version_number"] for version in versions] == [2, 1]

    document_response = client.get(f"/documents/{payload_one['document_id']}")
    assert document_response.status_code == 200
    assert document_response.json()["external_id"] == "contract-001"
    assert document_response.json()["original_filename"] == "v2.pdf"


def test_upload_same_external_id_and_hash_is_deduplicated(client) -> None:
    fixture = Path("tests/fixtures/sample.pdf")
    with fixture.open("rb") as handle:
        response_one = client.post(
            "/documents/upload?auto_submit=false",
            data={"external_id": "contract-002"},
            files={"file": ("sample.pdf", handle, "application/pdf")},
        )
    with fixture.open("rb") as handle:
        response_two = client.post(
            "/documents/upload?auto_submit=false",
            data={"external_id": "contract-002"},
            files={"file": ("sample.pdf", handle, "application/pdf")},
        )

    assert response_one.status_code == 200
    assert response_two.status_code == 200

    payload_one = response_one.json()
    payload_two = response_two.json()
    assert payload_one["document_id"] == payload_two["document_id"]
    assert payload_one["version_id"] == payload_two["version_id"]
    assert payload_two["deduplicated"] is True

    versions_response = client.get(f"/documents/{payload_one['document_id']}/versions")
    assert versions_response.status_code == 200
    assert len(versions_response.json()) == 1
