#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import os
import tempfile
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_ROOT = Path(
    os.getenv(
        "MEGADOC_ARCHIVE_GOLD_DIR",
        str(Path.home() / ".local/share/megadoc/archive-gold"),
    )
)
DEFAULT_MANIFEST = DEFAULT_DATA_ROOT / "archive_corpus.tsv"
DEFAULT_SUGGESTIONS = DEFAULT_DATA_ROOT / "page_annotations.json"
DEFAULT_OUTPUT = DEFAULT_DATA_ROOT / "archive_human_annotations.json"
STATIC_ROOT = ROOT / "tools/archive-annotator"


def load_cases(manifest: Path) -> list[dict[str, object]]:
    return [
        {
            **row,
            "bytes": int(row["bytes"]),
            "pages": int(row["pages"]),
        }
        for row in csv.DictReader(manifest.open(encoding="utf-8"), delimiter="\t")
    ]


def empty_annotations() -> dict[str, object]:
    return {
        "schema_version": 1,
        "updated_at": None,
        "documents": {},
        "questions": [],
    }


def load_annotations(path: Path) -> dict[str, object]:
    if not path.exists():
        return empty_annotations()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Annotation file must contain a JSON object.")
    return {**empty_annotations(), **payload}


def save_annotations(path: Path, payload: dict[str, object]) -> None:
    payload = {**payload, "schema_version": 1, "updated_at": datetime.now(timezone.utc).isoformat()}
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def normalize_annotations(
    cases: list[dict[str, object]], payload: dict[str, object]
) -> dict[str, object]:
    documents = payload.get("documents") if isinstance(payload.get("documents"), dict) else {}
    for case in cases:
        case_id = str(case["case_id"])
        annotation = documents.get(case_id)
        if not isinstance(annotation, dict):
            continue
        migrated = False
        entities = annotation.get("entities")
        if isinstance(entities, list):
            normalized_entities = []
            for entity in entities:
                if isinstance(entity, str):
                    normalized_entities.append({"entity_type": "unknown", "value": entity})
                    migrated = True
                elif isinstance(entity, dict):
                    normalized_entities.append(entity)
            annotation["entities"] = normalized_entities
        units = annotation.get("document_units")
        if not isinstance(units, list) or not units:
            units = [{
                "start_page": 1,
                "end_page": int(case["pages"]),
                "document_type": annotation.get("document_type") or "altro",
                "title": annotation.get("title") or "",
            }]
            annotation["document_units"] = units
            migrated = True
        legacy_specialist = annotation.get("specialist")
        for unit in units:
            if not isinstance(unit, dict) or isinstance(unit.get("specialist"), dict):
                continue
            document_type = str(unit.get("document_type") or "")
            kind = (
                "payable" if document_type in {"bolletta", "fattura"}
                else "accounting" if document_type in {"rendiconto_contabile", "riparto_spese", "preventivo"}
                else "none"
            )
            if len(units) == 1 and isinstance(legacy_specialist, dict) and legacy_specialist.get("kind") != "none":
                unit["specialist"] = dict(legacy_specialist)
            else:
                unit["specialist"] = {"kind": kind}
            migrated = True
        if "specialist" in annotation:
            del annotation["specialist"]
            migrated = True
        if migrated:
            annotation["reviewed"] = False
    payload["documents"] = documents
    return payload


def annotation_progress(cases: list[dict[str, object]], payload: dict[str, object]) -> dict[str, object]:
    documents = payload.get("documents") if isinstance(payload.get("documents"), dict) else {}
    reviewed = 0
    units = 0
    payable_cases = 0
    accounting_cases = 0
    for case in cases:
        annotation = documents.get(case["case_id"])
        if not isinstance(annotation, dict):
            continue
        if annotation.get("reviewed") is True:
            reviewed += 1
        document_units = annotation.get("document_units")
        if isinstance(document_units, list):
            units += len(document_units)
            for unit in document_units:
                specialist = unit.get("specialist") if isinstance(unit, dict) else None
                if isinstance(specialist, dict) and specialist.get("kind") == "payable":
                    payable_cases += 1
                if isinstance(specialist, dict) and specialist.get("kind") == "accounting":
                    accounting_cases += 1
    questions = payload.get("questions") if isinstance(payload.get("questions"), list) else []
    return {
        "documents_total": len(cases),
        "documents_reviewed": reviewed,
        "document_units": units,
        "payable_cases": payable_cases,
        "accounting_cases": accounting_cases,
        "questions": len(questions),
        "complete": reviewed == len(cases) and payable_cases >= 10 and accounting_cases >= 10 and len(questions) >= 30,
    }


def make_handler(
    *, manifest: Path, corpus_root: Path, suggestions: Path, output: Path
) -> type[BaseHTTPRequestHandler]:
    cases = load_cases(manifest)
    cases_by_id = {str(case["case_id"]): case for case in cases}

    class AnnotationHandler(BaseHTTPRequestHandler):
        server_version = "MegadocArchiveAnnotator/1"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/state":
                annotations = normalize_annotations(cases, load_annotations(output))
                suggestion_payload = (
                    json.loads(suggestions.read_text(encoding="utf-8"))
                    if suggestions.is_file()
                    else {"schema_version": 1, "documents": []}
                )
                self._json({
                    "cases": cases,
                    "annotations": annotations,
                    "orientation_suggestions": suggestion_payload,
                    "progress": annotation_progress(cases, annotations),
                })
                return
            if parsed.path.startswith("/api/pdf/"):
                case_id = unquote(parsed.path.removeprefix("/api/pdf/"))
                case = cases_by_id.get(case_id)
                if case is None:
                    self.send_error(HTTPStatus.NOT_FOUND, "Unknown case")
                    return
                self._file(corpus_root / str(case["relative_path"]), "application/pdf", allow_ranges=True)
                return
            relative = "index.html" if parsed.path in {"", "/"} else parsed.path.lstrip("/")
            target = (STATIC_ROOT / relative).resolve()
            if STATIC_ROOT.resolve() not in target.parents and target != STATIC_ROOT.resolve():
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            if not target.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._file(target, mimetypes.guess_type(target.name)[0] or "application/octet-stream")

        def do_HEAD(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/pdf/"):
                case_id = unquote(parsed.path.removeprefix("/api/pdf/"))
                case = cases_by_id.get(case_id)
                if case is None:
                    self.send_error(HTTPStatus.NOT_FOUND, "Unknown case")
                    return
                self._file(
                    corpus_root / str(case["relative_path"]),
                    "application/pdf",
                    allow_ranges=True,
                    head_only=True,
                )
                return
            relative = "index.html" if parsed.path in {"", "/"} else parsed.path.lstrip("/")
            target = (STATIC_ROOT / relative).resolve()
            if not target.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._file(
                target,
                mimetypes.guess_type(target.name)[0] or "application/octet-stream",
                head_only=True,
            )

        def do_PUT(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/api/annotations":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 5_000_000:
                    raise ValueError("Invalid request size")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("Expected JSON object")
                save_annotations(output, payload)
                saved = load_annotations(output)
                self._json({"saved": True, "progress": annotation_progress(cases, saved)})
            except (ValueError, json.JSONDecodeError) as exc:
                self._json({"saved": False, "error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

        def _json(self, payload: object, *, status: HTTPStatus = HTTPStatus.OK) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _file(
            self, path: Path, content_type: str, *, allow_ranges: bool = False, head_only: bool = False
        ) -> None:
            if not path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            size = path.stat().st_size
            start, end = 0, size - 1
            range_header = self.headers.get("Range") if allow_ranges else None
            if range_header and range_header.startswith("bytes="):
                raw_start, _, raw_end = range_header[6:].partition("-")
                start = int(raw_start) if raw_start else 0
                end = int(raw_end) if raw_end else end
                end = min(end, size - 1)
                self.send_response(HTTPStatus.PARTIAL_CONTENT)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            else:
                self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            if head_only:
                return
            with path.open("rb") as handle:
                handle.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = handle.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def log_message(self, format: str, *args: object) -> None:
            print(f"[annotator] {self.address_string()} {format % args}")

    return AnnotationHandler


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local Megadoc archive annotation UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--corpus-root", default=str(Path.home() / "Pisa"))
    parser.add_argument("--suggestions", default=str(DEFAULT_SUGGESTIONS))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    if not Path(args.manifest).is_file():
        parser.error(
            f"Private corpus manifest not found: {args.manifest}. "
            "Set --manifest or MEGADOC_ARCHIVE_GOLD_DIR."
        )
    handler = make_handler(
        manifest=Path(args.manifest), corpus_root=Path(args.corpus_root),
        suggestions=Path(args.suggestions), output=Path(args.output),
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Megadoc archive annotator: http://{args.host}:{args.port}")
    print(f"Annotations: {args.output}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
