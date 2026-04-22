import json
from pathlib import Path
from typing import Any

import httpx
import typer

from common.config import get_settings

app = typer.Typer(help="Bulk ingestion CLI for megadoc")
settings = get_settings()


def _print(payload: Any, output_json: bool) -> None:
    if output_json:
        typer.echo(json.dumps(payload, indent=2, default=str))
    else:
        typer.echo(payload)


def _client() -> httpx.Client:
    return httpx.Client(base_url=settings.api_base_url, timeout=settings.request_timeout_seconds)


@app.command("upload")
def upload(
    path: Path,
    auto_submit: bool = True,
    external_id: str | None = None,
    json_output: bool = False,
) -> None:
    with _client() as client, path.open("rb") as handle:
        response = client.post(
            "/documents/upload",
            params={"auto_submit": str(auto_submit).lower()},
            data={"external_id": external_id} if external_id else None,
            files={"file": (path.name, handle, "application/pdf")},
        )
        response.raise_for_status()
        _print(response.json(), json_output)


@app.command("bulk")
def bulk(
    path: Path,
    recursive: bool = False,
    auto_submit: bool = True,
    json_output: bool = False,
) -> None:
    files = path.rglob("*.pdf") if recursive else path.glob("*.pdf")
    results: list[dict[str, Any]] = []
    for candidate in sorted(files):
        try:
            with _client() as client, candidate.open("rb") as handle:
                response = client.post(
                    "/documents/upload",
                    params={"auto_submit": str(auto_submit).lower()},
                    files={"file": (candidate.name, handle, "application/pdf")},
                )
                response.raise_for_status()
                results.append({"path": str(candidate), "result": response.json(), "status": "ok"})
        except Exception as exc:
            results.append({"path": str(candidate), "status": "error", "error": str(exc)})
    _print(results, json_output)


@app.command("submit-job")
def submit_job(document_id: str, priority: int = 5, json_output: bool = False) -> None:
    with _client() as client:
        response = client.post("/jobs/ingest", json={"document_id": document_id, "priority": priority})
        response.raise_for_status()
        _print(response.json(), json_output)


@app.command("status")
def status(job_id: str, json_output: bool = False) -> None:
    with _client() as client:
        response = client.get(f"/jobs/{job_id}")
        response.raise_for_status()
        _print(response.json(), json_output)


@app.command("reprocess")
def reprocess(document_id: str, json_output: bool = False) -> None:
    submit_job(document_id=document_id, json_output=json_output)


if __name__ == "__main__":
    app()
