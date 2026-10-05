#!/usr/bin/env python3
"""Independent vision transcription of uncertain archived OCR pages, read-only."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import time

import fitz
import httpx

from compare_archived_ocr import save
from ocr_corpus_metrics import concordance, numbers

ROOT = Path(__file__).resolve().parents[1]
PROMPT = (
    "Transcribe this scanned page faithfully in its original language. Return only the transcription, "
    "not a summary or an explanation. Preserve visible headings, handwritten annotations, dates, "
    "amounts, addresses and marginal text. Use HTML tables for visible tables, preserving rows and "
    "columns. Do not invent content or fill blank cells. Mark unreadable text [illeggibile]. "
    "Do not infer text from a logo, document type or customary wording. "
    "If the scan is rotated, read it in the appropriate direction. If text is mirrored, "
    "faint or visible through paper, transcribe only characters you can actually identify."
)


def select_pages(rows, per_group=6):
    selected = {}
    def add(row, reason):
        key = (row["ocr_result_id"], row["page"])
        item = selected.setdefault(key, {"ocr_result_id": key[0], "page": key[1],
                                         "document_id": row["document_id"], "reasons": []})
        if reason not in item["reasons"]:
            item["reasons"].append(reason)
    for row in rows:
        if row["int8"]["status"] != "ok":
            add(row, "glm_failed")
    ok = [r for r in rows if r["int8"]["status"] == "ok"]
    for metric, reason in (("word_sequence_agreement_not_accuracy", "low_word_agreement"),
                          ("numeric_retention_not_accuracy", "low_numeric_retention")):
        candidates = [r for r in ok if r["int8"]["concordance"].get(metric) is not None
                      and (reason != "low_numeric_retention" or
                           r["int8"]["concordance"]["reference_numeric_occurrences"] >= 10)]
        seen = set()
        for row in sorted(candidates, key=lambda r: (r["int8"]["concordance"][metric],
                                                    r["ocr_result_id"], r["page"])):
            if row["document_id"] in seen:
                continue
            add(row, reason)
            seen.add(row["document_id"])
            if len(seen) >= per_group:
                break
    # High-agreement controls with substantive text, not empty or nearly empty pages.
    seen = set()
    controls = sorted(ok, key=lambda r: r["int8"]["concordance"]["word_sequence_agreement_not_accuracy"], reverse=True)
    for row in controls:
        scores = row["int8"]["concordance"]
        if row["document_id"] in seen or scores["reference_words"] < 100:
            continue
        if scores["word_sequence_agreement_not_accuracy"] < .95 or scores["numeric_retention_not_accuracy"] != 1:
            continue
        add(row, "high_agreement_control")
        seen.add(row["document_id"])
        if len(seen) == 2:
            break
    return list(selected.values())


def numeric_diff(reference, candidate):
    left, right = numbers(reference), numbers(candidate)
    return {"reference_only": list((left-right).elements()),
            "candidate_only": list((right-left).elements())}


def transcription_text(raw):
    lines = (raw or "").strip().splitlines()
    if len(lines) >= 3 and lines[0].strip().lower() in {"```", "```html", "```markdown"} and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1])
    return raw or ""


def write_comparison(output):
    pages = []
    for path in sorted(output.glob("*/page-*.json")):
        record = json.loads(path.read_text())
        item = {k: record[k] for k in ("ocr_result_id", "document_id", "page", "status", "seconds", "reasons")}
        item["rotation_delta"] = record.get("rotation_delta", 0)
        item["finish_reason"] = record["response"].get("choices", [{}])[0].get("finish_reason")
        if record["status"] == "ok":
            text = transcription_text(record["response"]["choices"][0]["message"].get("content"))
            dots = record["dots"].get("markdown") or record["dots"].get("text") or ""
            item["dots_qwen"] = concordance(dots, text)
            item["dots_qwen_numbers"] = numeric_diff(dots, text)
            if record["glm"]["status"] == "ok":
                glm = record["glm"]["page"]["markdown"]
                item["glm_qwen"] = concordance(glm, text)
                item["glm_qwen_numbers"] = numeric_diff(glm, text)
        pages.append(item)
    save(output / "comparison.json", {"analysis_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
         "warning": "Targeted disagreement sample, not an accuracy estimate. Raw responses unchanged. HTML outer fences removed for scoring.",
         "pages": pages, "successful": sum(p["status"] == "ok" for p in pages),
         "failed": sum(p["status"] != "ok" for p in pages)})


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--endpoint", default="http://host.docker.internal:18020/v1")
    ap.add_argument("--model", default="qwen3.8-27b")
    ap.add_argument("--per-group", type=int, default=6)
    ap.add_argument("--prepare-only", action="store_true")
    ap.add_argument("--report-only", action="store_true")
    ap.add_argument("--case", nargs=3, action="append", metavar=("OCR_ID", "PAGE", "ROTATION_DELTA"),
                    help="Explicit page and supplementary right-angle rotation")
    ap.add_argument("--glm-endpoint", help="Also run GLM on the supplementary image")
    args = ap.parse_args()
    if args.output.resolve() == ROOT or ROOT in args.output.resolve().parents:
        ap.error("Private evidence must remain outside Git")
    if args.per_group < 1:
        ap.error("per-group must be positive")
    args.output.mkdir(mode=0o700, parents=True, exist_ok=True)
    if args.report_only:
        write_comparison(args.output)
        return
    rows = [json.loads(p.read_text()) for p in sorted(args.corpus.glob("*/pair-*.json"))]
    source_manifest = json.loads((args.corpus / "manifest.json").read_text())
    hashes = {c["ocr_result_id"]: c["normalized_sha256"] for c in source_manifest["cases"]}
    selected = select_pages(rows, args.per_group)
    if args.case:
        indexed = {(r["ocr_result_id"], r["page"]): r for r in rows}
        selected = []
        for case, page, rotation in args.case:
            page, rotation = int(page), int(rotation)
            if rotation not in (0, 90, 180, 270) or (case, page) not in indexed:
                ap.error("Case must exist and rotation must be a right angle")
            selected.append({"ocr_result_id": case, "page": page,
                             "document_id": indexed[case, page]["document_id"],
                             "reasons": ["manual_orientation_hypothesis"], "rotation_delta": rotation})
    manifest = {"selection": selected, "endpoint": args.endpoint,
                "glm_endpoint": args.glm_endpoint,
                "model": args.model, "prompt": PROMPT, "render_dpi": 200, "max_tokens": 8192,
                "corpus_manifest_sha256": hashlib.sha256((args.corpus / "manifest.json").read_bytes()).hexdigest(),
                "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    path = args.output / "manifest.json"
    if path.exists() and json.loads(path.read_text()) != manifest:
        raise ValueError("Experiment changed; use a new output directory")
    save(path, manifest)
    print(json.dumps({"selected_pages": len(manifest["selection"]), "selection": manifest["selection"]}), flush=True)
    if args.prepare_only:
        return
    with httpx.Client(timeout=900) as client:
        response = client.get(args.endpoint.rstrip("/") + "/models")
        response.raise_for_status()
        save(args.output / "models.json", response.json())
        if args.model not in [m["id"] for m in response.json()["data"]]:
            raise ValueError("Requested Qwen model not served")
        for item in manifest["selection"]:
            directory = args.output / item["ocr_result_id"]
            directory.mkdir(mode=0o700, exist_ok=True)
            output = directory / f"page-{item['page']:04d}.json"
            if output.exists():
                continue
            source = args.corpus / item["ocr_result_id"]
            pdf = source / "normalized.pdf"
            if hashlib.sha256(pdf.read_bytes()).hexdigest() != hashes[item["ocr_result_id"]]:
                raise ValueError("Archived normalized source changed")
            baseline = json.loads((source / "dots.json").read_text())["structured_json"]["pages"][item["page"]-1]
            glm = json.loads((source / f"page-{item['page']:04d}-int8.json").read_text())
            with fitz.open(pdf) as document:
                page = document[item["page"]-1]
                page.set_rotation((page.rotation + item.get("rotation_delta", 0)) % 360)
                image = page.get_pixmap(matrix=fitz.Matrix(200/72, 200/72), alpha=False)
                png = image.tobytes("png")
                image.save(directory / f"page-{item['page']:04d}.png")
            archived_glm = glm
            if args.glm_endpoint:
                start = time.monotonic()
                response = client.post(args.glm_endpoint.rstrip("/") + "/parse", json={
                    "model": "glm-ocr", "max_tokens": 8192,
                    "document": "data:image/png;base64," + base64.b64encode(png).decode()})
                glm = {"status": "failed", "seconds": time.monotonic()-start,
                       "http_status": response.status_code, "response": response.json()}
                if response.is_success:
                    glm.update(status="ok", page={"markdown": response.json()["markdown"]})
            request = {"model": args.model, "temperature": 0, "max_tokens": 8192,
                       "chat_template_kwargs": {"enable_thinking": False},
                       "messages": [{"role": "user", "content": [
                           {"type": "text", "text": PROMPT},
                           {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}]}]}
            save(directory / f"request-{item['page']:04d}.json", request)
            save(args.output / "current.json", item)
            start = time.monotonic()
            response = client.post(args.endpoint.rstrip("/") + "/chat/completions", json=request)
            record = {**item, "seconds": time.monotonic()-start, "http_status": response.status_code,
                      "image_sha256": hashlib.sha256(png).hexdigest(), "response": response.json(),
                      "dots": baseline, "glm": glm, "archived_glm": archived_glm, "status": "failed"}
            if response.is_success:
                choice = record["response"]["choices"][0]
                text = transcription_text(choice["message"].get("content"))
                record["qwen_text"] = text
                if choice.get("finish_reason") == "stop" and text.strip():
                    record["status"] = "ok"
                    dots = baseline.get("markdown") or baseline.get("text") or ""
                    record["dots_qwen"] = concordance(dots, text)
                    record["dots_qwen_numbers"] = numeric_diff(dots, text)
                    if glm["status"] == "ok":
                        record["glm_qwen"] = concordance(glm["page"]["markdown"], text)
                        record["glm_qwen_numbers"] = numeric_diff(glm["page"]["markdown"], text)
            save(output, record)
            print(json.dumps({**item, "status": record["status"], "seconds": round(record["seconds"], 2),
                              "dots_qwen": record.get("dots_qwen"), "glm_qwen": record.get("glm_qwen")}), flush=True)
            response.raise_for_status()  # Stop on server/configuration errors, no retry or fallback.
    save(args.output / "current.json", {"state": "finished"})
    write_comparison(args.output)


if __name__ == "__main__":
    main()
