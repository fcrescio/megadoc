#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import os
import tempfile
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html.parser import HTMLParser
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
        "schema_version": 3,
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
    payload = {**payload, "schema_version": 3, "updated_at": datetime.now(timezone.utc).isoformat()}
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
        incomplete_structured_specialist = False
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
        for unit in units:
            if not isinstance(unit, dict):
                continue
            specialist = unit.get("specialist")
            if not isinstance(specialist, dict):
                continue
            if specialist.get("kind") == "payable":
                defaults = {
                    "payable_kind": "utility_bill" if unit.get("document_type") == "bolletta" else "invoice",
                    "currency": "EUR",
                    "issue_date": "",
                    "subject": specialist.get("subject") or "",
                    "payment_status": "unknown",
                }
                for key, value in defaults.items():
                    if key not in specialist:
                        specialist[key] = value
            if specialist.get("kind") == "accounting":
                if "statement_type" not in specialist:
                    specialist["statement_type"] = "unknown"
                if "period_from" not in specialist:
                    specialist["period_from"] = ""
                    specialist["period_to"] = ""
                table_pages = normalize_page_spec(
                    str(specialist.get("table_pages") or ""),
                    start_page=int(unit.get("start_page") or 1),
                    end_page=int(unit.get("end_page") or 1),
                )
                normalized_page_spec = ",".join(str(page) for page in table_pages)
                if normalized_page_spec and normalized_page_spec != specialist.get("table_pages"):
                    specialist["table_pages"] = normalized_page_spec
                if not isinstance(specialist.get("checks"), list):
                    specialist["checks"] = parse_legacy_accounting_checks(
                        str(specialist.get("cell_checks") or ""),
                        start_page=int(unit.get("start_page") or 1),
                        end_page=int(unit.get("end_page") or 1),
                    )
                if not isinstance(specialist.get("gold_tables"), list):
                    specialist["gold_tables"] = []
                    specialist["tables_reviewed"] = False
                if specialist.get("tables_reviewed") is not True or not specialist["gold_tables"]:
                    incomplete_structured_specialist = True
        if "specialist" in annotation:
            del annotation["specialist"]
            migrated = True
        if migrated or incomplete_structured_specialist:
            annotation["reviewed"] = False
    payload["documents"] = documents
    payload["schema_version"] = 3
    return payload


def fetch_accounting_tables(api_base_url: str, case_id: str) -> dict[str, object]:
    base = api_base_url.rstrip("/")
    with urllib.request.urlopen(f"{base}/documents", timeout=15) as response:
        documents = json.load(response)
    document = next(
        (
            item for item in documents
            if isinstance(item, dict) and str(item.get("external_id") or "") == case_id
        ),
        None,
    )
    if document is None:
        return {"case_id": case_id, "document_id": None, "tables": [], "status": "document_not_loaded"}
    document_id = str(document["id"])
    with urllib.request.urlopen(
        f"{base}/knowledge/documents/{document_id}/accounting-raw-tables", timeout=30
    ) as response:
        payload = json.load(response)
    tables = payload.get("tables") if isinstance(payload, dict) else []
    status = "available"
    if not isinstance(tables, list) or not tables:
        with urllib.request.urlopen(f"{base}/documents/{document_id}/ocr", timeout=30) as response:
            ocr = json.load(response)
        tables = accounting_tables_from_ocr(ocr)
        status = "ocr_fallback"
    return {
        "case_id": case_id,
        "document_id": document_id,
        "tables": tables if isinstance(tables, list) else [],
        "status": status,
    }


class _HTMLGoldTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[tuple[str, bool]]] = []
        self._row: list[tuple[str, bool]] | None = None
        self._cell: list[str] | None = None
        self._header = False
        self._colspan = 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []
            self._header = tag == "th"
            values = dict(attrs)
            try:
                self._colspan = max(1, int(values.get("colspan") or 1))
            except ValueError:
                self._colspan = 1
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            value = " ".join("".join(self._cell).split())
            self._row.append((value, self._header))
            self._row.extend(("", self._header) for _ in range(self._colspan - 1))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def parse_html_gold_table(html: str) -> tuple[list[str], list[dict[str, object]]] | None:
    parser = _HTMLGoldTableParser()
    parser.feed(html)
    rows = [row for row in parser.rows if row]
    if not rows:
        return None
    width = max(len(row) for row in rows)
    first_is_header = any(is_header for _, is_header in rows[0])
    if first_is_header:
        raw_headers = [value for value, _ in rows.pop(0)]
    else:
        raw_headers = [f"Colonna {index}" for index in range(1, width + 1)]
    headers: list[str] = []
    for index in range(width):
        base = (raw_headers[index] if index < len(raw_headers) else "").strip() or f"Colonna {index + 1}"
        candidate, suffix = base, 2
        while candidate in headers:
            candidate = f"{base} ({suffix})"
            suffix += 1
        headers.append(candidate)
    parsed_rows = []
    for index, row in enumerate(rows, start=1):
        values = [value for value, _ in row] + [""] * (width - len(row))
        parsed_rows.append({
            "row_id": f"row_{index}",
            "cells": dict(zip(headers, values, strict=True)),
        })
    return headers, parsed_rows


def accounting_tables_from_ocr(payload: dict[str, object]) -> list[dict[str, object]]:
    structured = payload.get("structured_json") if isinstance(payload, dict) else None
    if not isinstance(structured, dict):
        return []
    pages = structured.get("pages")
    if not isinstance(pages, list):
        return []
    orientation = structured.get("orientation_preprocess")
    reversed_order = isinstance(orientation, dict) and orientation.get("page_order_reversed") is True
    page_count = int(payload.get("page_count") or len(pages))
    output: list[dict[str, object]] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        normalized_page = int(page.get("page_number") or page.get("page_no") or 0)
        source_page = page_count + 1 - normalized_page if reversed_order else normalized_page
        for table_index, table in enumerate(page.get("tables") or [], start=1):
            if not isinstance(table, dict):
                continue
            html = next(
                (
                    cell.get("html") for cell in table.get("cells") or []
                    if isinstance(cell, dict) and isinstance(cell.get("html"), str)
                ),
                None,
            )
            parsed = parse_html_gold_table(html) if html else None
            if parsed is None:
                continue
            headers, rows = parsed
            output.append({
                "table_id": table.get("id") or f"page-{normalized_page}-table-{table_index}",
                "table_type": "unknown",
                "page_number": source_page,
                "title": table.get("caption") or "",
                "headers": headers,
                "rows": rows,
                "source": "ocr_structured",
            })
    return output


def normalize_page_spec(value: str, *, start_page: int, end_page: int) -> list[int]:
    pages: list[int] = []
    for token in value.replace(";", ",").split(","):
        token = token.strip().lower().removeprefix("pg.").removeprefix("p.").strip()
        if not token:
            continue
        try:
            if "-" in token:
                left, right = token.split("-", 1)
                candidates = list(range(int(left), int(right) + 1))
            else:
                candidates = [int(token)]
        except ValueError:
            continue
        for page in candidates:
            if not start_page <= page <= end_page and 1 <= page <= end_page - start_page + 1:
                page = start_page + page - 1
            if start_page <= page <= end_page and page not in pages:
                pages.append(page)
    return sorted(pages)


def parse_legacy_accounting_checks(
    value: str, *, start_page: int, end_page: int
) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    for line in value.splitlines():
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 3:
            continue
        page_candidates = normalize_page_spec(parts[0], start_page=start_page, end_page=end_page)
        if not page_candidates:
            continue
        expected = parts[-1]
        try:
            Decimal(expected.replace(".", "").replace(",", ".") if "," in expected else expected)
            comparison = "amount"
        except InvalidOperation:
            comparison = "exact"
        middle = parts[1:-1]
        checks.append({
            "page": page_candidates[0],
            "table": middle[0] if middle else "",
            "row": middle[1] if len(middle) > 1 else "",
            "column": middle[2] if len(middle) > 2 else "",
            "expected": expected,
            "comparison": comparison,
        })
    return checks


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
    *, manifest: Path, corpus_root: Path, suggestions: Path, output: Path,
    api_base_url: str = "http://127.0.0.1:8080",
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
            if parsed.path.startswith("/api/accounting-tables/"):
                case_id = unquote(parsed.path.removeprefix("/api/accounting-tables/"))
                if case_id not in cases_by_id:
                    self.send_error(HTTPStatus.NOT_FOUND, "Unknown case")
                    return
                try:
                    self._json(fetch_accounting_tables(api_base_url, case_id))
                except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
                    self._json(
                        {"case_id": case_id, "status": "api_error", "tables": [], "error": str(exc)},
                        status=HTTPStatus.BAD_GATEWAY,
                    )
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
                if length <= 0 or length > 50_000_000:
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
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8080")
    args = parser.parse_args()
    if not Path(args.manifest).is_file():
        parser.error(
            f"Private corpus manifest not found: {args.manifest}. "
            "Set --manifest or MEGADOC_ARCHIVE_GOLD_DIR."
        )
    handler = make_handler(
        manifest=Path(args.manifest), corpus_root=Path(args.corpus_root),
        suggestions=Path(args.suggestions), output=Path(args.output),
        api_base_url=args.api_base_url,
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
