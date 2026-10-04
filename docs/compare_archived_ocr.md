# Comparing an archived OCR result with new backends

`scripts/compare_archived_ocr.py` compares an archived `dots_native` result with
the actual GLM and `llm_vision` adapters. It does not change the selected backend,
write database rows, enqueue jobs, or rerun knowledge/specialist extraction.

## Run

Choose archived document UUIDs, starting with one short document. Store evidence
outside the repository. The account running the container must be able to write
to the mounted evidence directory.

```bash
EVIDENCE="$HOME/megadoc-ocr-benchmarks/experiment-1"
install -d -m 700 "$EVIDENCE"
docker compose run --rm --no-deps --user "$(id -u):$(id -g)" \
  -v "$PWD:/app" -v "$EVIDENCE:/evidence" \
  api python scripts/compare_archived_ocr.py --output /evidence DOCUMENT_UUID
```

Endpoints and the Qwen model can be supplied explicitly with `--glm-endpoint`,
`--qwen-endpoint`, and `--qwen-model`. Defaults match the local experimental
servers on ports 18030 and 18020. Backend timeout is 600 seconds for Qwen;
GLM uses its configured timeout. Render scale is 1.5 for both adapters.

## Evidence and controls

For each UUID the script saves:

- `dots.json`: complete historical row, model, version and extraction metadata.
- `original.pdf`: the precise document version referenced by that OCR row.
- `normalized.pdf` and `page_mapping.json`: archived orientation and page order
  replayed, including any per-page dots render rotation.
- `manifest.json`: source checksums, endpoints, models, rendering and token limits.
- `glm.json` and `qwen.json`: new adapter results, timing, table counts and errors.
- `*-requests.json`: raw responses checkpointed after each request, including
  usage and finish reason. Truncated responses are explicitly flagged.
- `comparison.json`: summary and numeric/text concordance against the baseline.

Database access is explicitly read-only. Saved sources are checksum-verified on
resume. Existing results are reused; incompatible manifest settings are rejected.
Use a new evidence directory for a new experiment or retry. An adapter exception
does not discard previous page responses or prevent the other backend from running.

Requests are sequential. The models receive the same normalized PDF and page
render scale, but use their native production prompts and output contracts:
GLM emits Markdown/HTML, whereas `llm_vision` requests structured JSON. Internal
image preprocessing, tokenization and hardware differ. These timings compare
the complete OCR adapters, not isolated model architectures.

## Verification

Start with a small document and inspect its saved source and both outputs. Check
page count, orientation, model, finish reasons and critical numbers. Only then
extend to documents containing tables, dense prose and mixed scan orientations.

Check the database result count/content checksum before and after the experiment
to confirm the archive was not modified. No deployment rebuild is needed for
this standalone tool; run it with the repository mounted into the API image.

Text agreement and numeric overlap are **not accuracy**: the baseline may have
errors, reordered text, different separators or hallucinated headers. The numeric
metric is literal and does not normalize number formats. Inspect critical values
against source images; do not use agreement scores as acceptance thresholds.
CER/WER requires a separate, verified gold transcription.

Compare structured tables separately from tables present in Markdown. Successful
OCR text does not imply all downstream table consumers receive usable structures.
Neither GLM nor Qwen currently provides dots-equivalent geometric layout evidence.

## Orientation follow-up

A supplementary run can use explicit page rotations with `--page-rotations`,
for example `--page-rotations 270,270,90,90` for one four-page document. Determine
these rotations by inspecting the source. Use a **different evidence directory**.
This is not a result from the existing production orientation detector and must
not be mixed with the archived-input comparison. The overrides are recorded in
the manifest and page mapping.

## Privacy

PDFs, raw OCR, request responses and visual annotations are private evidence.
They must remain outside Git. Only tooling, deterministic synthetic tests and
an anonymized aggregate report belong in the repository.
