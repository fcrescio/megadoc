#!/usr/bin/env python3
"""Read-only, resumable dots/GLM FP16/GLM INT8 corpus benchmark."""
import argparse
import base64
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/common/src"))

import fitz
import httpx
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from common.config import get_settings
from common.db.models import DocumentVersion, OCRResult
from common.processing.glm_ocr import structured_sdk_page
from common.storage.backends import get_storage_backend
from compare_archived_ocr import normalized_pdf, save
from ocr_corpus_metrics import concordance, summarize, table_profile


def stamp():
    return datetime.now(timezone.utc).isoformat()


def prepare(output, settings, experiment):
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest["experiment"] != experiment:
            raise ValueError("Experiment changed: use a new evidence directory")
        return manifest
    engine = create_engine(settings.database_url)
    storage = get_storage_backend(settings)
    cases = []
    with Session(engine) as session:
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        results = session.scalars(select(OCRResult).where(OCRResult.engine_name == "dots_native")
                                  .order_by(OCRResult.created_at, OCRResult.id)).all()
        fingerprint = session.execute(text("SELECT count(*),md5(string_agg(id::text || md5(full_text) || "
            "md5(structured_json::text), '' ORDER BY id)) FROM ocr_results")).one()
        for result in results:
            directory = output / str(result.id)
            directory.mkdir(mode=0o700, exist_ok=True)
            baseline = {column.name: getattr(result, column.name) for column in OCRResult.__table__.columns}
            version = session.get(DocumentVersion, result.document_version_id)
            if version is None:
                raise ValueError(f"Missing source version for OCR {result.id}")
            original = storage.read_bytes(version.storage_bucket, version.storage_object_key)
            baseline["source_sha256"] = hashlib.sha256(original).hexdigest()
            source, normalized = directory / "original.pdf", directory / "normalized.pdf"
            source.write_bytes(original)
            save(directory / "dots.json", baseline)
            mapping = normalized_pdf(source, normalized, baseline)
            save(directory / "page_mapping.json", mapping)
            with fitz.open(normalized) as pdf:
                source_pages = len(pdf)
            cases.append({"ocr_result_id": str(result.id), "document_id": str(result.document_id),
                "version_id": str(result.document_version_id), "historical_pages": result.page_count,
                "source_pages": source_pages, "historical_structured_pages": len((baseline.get("structured_json") or {}).get("pages") or []),
                "source_sha256": baseline["source_sha256"],
                "normalized_sha256": hashlib.sha256(normalized.read_bytes()).hexdigest()})
    engine.dispose()
    manifest = {"created_at": stamp(), "experiment": experiment, "cases": cases,
                "ocr_archive_fingerprint": list(fingerprint),
                "historical_results": len(cases), "distinct_documents": len({c["document_id"] for c in cases}),
                "historical_pages": sum(c["historical_pages"] for c in cases),
                "source_pages": sum(c["source_pages"] for c in cases),
                "warning": "Includes every dots result, including repeated runs of the same document."}
    save(manifest_path, manifest)
    return manifest


def baseline_page(baseline, index):
    pages = (baseline.get("structured_json") or {}).get("pages") or []
    if index >= len(pages):
        return None
    page = pages[index]
    number = page.get("page_number", page.get("page_no", index + 1))
    if number != index + 1:
        return None
    return page


def recognize(client, endpoint, image, directory, variant, index, dots, max_tokens, expected_metadata):
    path = directory / f"page-{index+1:04d}-{variant}.json"
    if path.exists():
        return json.loads(path.read_text())
    record = {"started_at": stamp(), "status": "failed"}
    start = time.monotonic()
    try:
        response = client.post(endpoint.rstrip("/") + "/parse", json={"model": "glm-ocr",
            "document": "data:image/png;base64," + base64.b64encode(image).decode(),
            "max_tokens": max_tokens})
        record["http_status"] = response.status_code
        record["seconds"] = time.monotonic() - start
        payload = response.json()
        record["response"] = payload
        response.raise_for_status()
        if any(payload.get("metadata", {}).get(key) != value for key, value in expected_metadata.items()):
            raise ValueError("GLM pipeline settings differ from frozen experiment")
        page = structured_sdk_page(index + 1, payload)
        record.update(status="ok", page=page, table_profile=table_profile(page))
        if dots is not None:
            record["concordance"] = concordance(dots.get("markdown") or dots.get("text") or "",
                                                 page["markdown"])
        else:
            record["status"] = "unmatched_baseline"
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    record.setdefault("seconds", time.monotonic() - start)
    record["finished_at"] = stamp()
    save(path, record)
    return record


def report(output, manifest, state, current=None):
    rows = []
    for case in manifest["cases"]:
        rows.extend(json.loads(p.read_text()) for p in sorted((output / case["ocr_result_id"]).glob("pair-*.json")))
    summary = summarize(rows, manifest["source_pages"], manifest["distinct_documents"], state, current)
    if state == "finished" and any(v["failed"] for v in summary["variants"].values()):
        state = summary["state"] = "finished_with_failures"
    summary["updated_at"] = stamp()
    summary["historical_results"] = manifest["historical_results"]
    summary["historical_pages"] = manifest["historical_pages"]
    summary["baseline_page_count_mismatches"] = [c for c in manifest["cases"]
        if c["source_pages"] != c["historical_structured_pages"] or c["source_pages"] != c["historical_pages"]]
    save(output / "summary.json", summary)
    lines = ["# OCR corpus benchmark", "", f"State: {state}",
             f"Updated: {summary['updated_at']}",
             f"Page pairs attempted: {len(rows)}/{manifest['source_pages']}", "",
             "Dots is NOT gold. Scores measure concordance, not accuracy.", "",
             "| Variant | Successful | Failed/unmatched | Mean word agreement | Mean numeric retention | Median seconds |",
             "| --- | --- | --- | --- | --- | --- |"]
    for variant, data in summary["variants"].items():
        fmt = lambda d, key='mean': f"{d[key]:.4f}" if key in d else "n/a"
        lines.append(f"| {variant} | {data['successful']} | {data['failed']} | "
                     f"{fmt(data['word_agreement'])} | {fmt(data['numeric_retention'])} | {fmt(data['latency_s'], 'median')} |")
    lines.extend(["", "Confidence intervals and paired/stratified statistics: `summary.json`.",
                  "Page comparisons: `<ocr-result-id>/pair-<page>.json`.",
                  "Raw responses and layout confidence: `<ocr-result-id>/page-<page>-<variant>.json`."])
    temporary = output / "REPORT.md.tmp"
    temporary.write_text("\n".join(lines) + "\n")
    temporary.replace(output / "REPORT.md")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--fp16-endpoint", default="http://host.docker.internal:18032/v1")
    parser.add_argument("--int8-endpoint", default="http://host.docker.internal:18031/v1")
    parser.add_argument("--model-manifest", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if output == ROOT or ROOT in output.parents:
        parser.error("Evidence must remain outside Git")
    if args.timeout <= 0 or not 1 <= args.max_tokens <= 8192:
        parser.error("Positive timeout and max tokens in 1..8192 required")
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (output / ".runner.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in
                  ("scripts/benchmark_ocr_corpus.py", "scripts/ocr_corpus_metrics.py",
                   "scripts/compare_archived_ocr.py", "packages/common/src/common/processing/glm_ocr.py")}
        experiment = {"endpoints": {"fp16": args.fp16_endpoint, "int8": args.int8_endpoint},
                      "model_manifest": json.loads(args.model_manifest.read_text()), "code_sha256": hashes,
                      "timeout": args.timeout, "max_tokens": args.max_tokens, "render_dpi": 200,
                      "orientation": "exact archived order/rotation replay; no manual upright corrections"}
        manifest = prepare(output, get_settings(), experiment)
        if args.prepare_only or args.report_only:
            report(output, manifest, "prepared" if args.prepare_only else "report_only")
            return
        baselines = {c["ocr_result_id"]: json.loads((output / c["ocr_result_id"] / "dots.json").read_text()) for c in manifest["cases"]}
        completed = 0
        try:
            with httpx.Client(timeout=args.timeout) as client:
                health = {}
                for variant, endpoint in experiment["endpoints"].items():
                    response = client.get(endpoint.rstrip("/").removesuffix("/v1") + "/health")
                    response.raise_for_status()
                    health[variant] = response.json()
                    if not health[variant].get("document_parsing"):
                        raise RuntimeError(f"SDK parsing unavailable: {variant}")
                save(output / "health.json", health)
                # First page of every result before second pages: broad early coverage.
                for index in range(max((c["source_pages"] for c in manifest["cases"]), default=0)):
                    for case in manifest["cases"]:
                        if index >= case["source_pages"]:
                            continue
                        directory = output / case["ocr_result_id"]
                        pair_path = directory / f"pair-{index+1:04d}.json"
                        if pair_path.exists():
                            completed += 1
                            continue
                        current = {"ocr_result_id": case["ocr_result_id"], "page": index + 1}
                        report(output, manifest, "running", current)
                        if hashlib.sha256((directory / "normalized.pdf").read_bytes()).hexdigest() != case["normalized_sha256"]:
                            raise ValueError("Normalized PDF checksum changed")
                        dots = baseline_page(baselines[case["ocr_result_id"]], index)
                        with fitz.open(directory / "normalized.pdf") as pdf:
                            image = pdf[index].get_pixmap(matrix=fitz.Matrix(200 / 72, 200 / 72), alpha=False).tobytes("png")
                        row = {**current, "document_id": case["document_id"], "dots_table_profile": table_profile(dots or {})}
                        order = ("fp16", "int8") if completed % 2 == 0 else ("int8", "fp16")
                        for variant in order:
                            save(output / "current.json", {**current, "variant": variant, "started_at": stamp()})
                            row[variant] = recognize(client, experiment["endpoints"][variant], image,
                                                     directory, variant, index, dots, args.max_tokens,
                                                     experiment["model_manifest"]["expected_parse_metadata"])
                            print(json.dumps({**current, "variant": variant, "status": row[variant]["status"],
                                              "seconds": round(row[variant]["seconds"], 3)}), flush=True)
                        if all(row[v]["status"] == "ok" for v in order):
                            row["fp16_int8"] = concordance(row["fp16"]["page"]["markdown"], row["int8"]["page"]["markdown"])
                        save(pair_path, row)
                        completed += 1
                report(output, manifest, "finished")
                save(output / "current.json", {"state": "finished", "finished_at": stamp()})
        except BaseException:
            report(output, manifest, "interrupted")
            raise


if __name__ == "__main__":
    main()
