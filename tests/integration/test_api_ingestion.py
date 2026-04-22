from pathlib import Path


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

