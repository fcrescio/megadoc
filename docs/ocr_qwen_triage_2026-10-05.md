# OCR: independent Qwen triage, 2026-10-05

## Scope and conclusion

This experiment compares independent Qwen vision transcription with frozen
dots.ocr archive output and the completed GLM-OCR INT8 corpus experiment.
It does not re-ingest documents, modify production OCR settings, or establish
a gold reference by majority vote.

The discrepancies have several distinct causes: accepted repetitions in the
dots archive, GLM generation failures on readable material, incorrect scan
orientation and reading order, missing regions, and genuinely difficult
handwriting or mirrored bleed-through. Qwen also fails on some inputs.
Replacing one engine with another is therefore not a sufficient correction.

## Runtime and protocol

- Exactly one Qwen instance was running: `qwen-optimization`, port 18020.
- `/v1/models` exposed `qwen3.8-27b`; requests used this base model, not its
  separately exposed LoRA adapter.
- Image requests succeeded. Vision is offloaded by this runtime; a startup
  message about disabled multimodal configuration is not proof of text-only
  operation. No second Qwen container was started and no runtime was replaced.
- GLM remained on the Intel iGPU, separate from Qwen's NVIDIA GPU.
- Both candidates received page images rendered at 200 DPI from frozen
  normalized PDFs. Source checksums were verified before inference.
- Qwen received a transcription prompt, temperature zero, disabled thinking,
  and a limit of 8192 generated tokens. Neither archived transcription was
  included in its prompt. No retry or engine fallback was applied.
- Full requests, images, responses, selection and source hashes are private
  local evidence, not Git fixtures.

The selection contains all five GLM failures, six low word-agreement pages
from distinct documents, six low numeric-retention pages from distinct
documents, and two substantial high-agreement controls. Overlaps are
deduplicated: **16 pages from 15 documents**. This deliberately adverse sample
cannot estimate whole-archive accuracy.

## Results

| Observation | Result | Interpretation |
| --- | --- | --- |
| Initial Qwen requests | 14 stopped normally; 2 reached the token limit | HTTP success alone is not extraction success |
| Five GLM failures | Qwen stopped normally on four | Completing a page does not establish correctness |
| Readable accounting page among GLM failures | Qwen/dots word agreement 95.9%; all 47 numeric occurrences match | The GLM failure cannot be attributed simply to illegible source material |
| Two controls | Word agreement 100% and 98.2%; 46/46 and 19/19 numeric occurrences match across engines | The request protocol works on ordinary legible pages |
| Three-column upside-down warranty | GLM/Qwen sequence agreement 17.1%, word-bag F1 93.7%; 21/22 GLM numeric occurrences also in Qwen | Reading order dominates this low sequence score; it is not wholesale text loss |
| Near-blank verso | GLM empty, Qwen unreadable marker, dots a few words | Zero agreement is not automatically a candidate failure |
| Archived dots repetitions | Repeated invoice headings, repeated zeros on a receipt, repeated payment identifiers/amounts on forms | The historical output is not a trustworthy numeric denominator on these pages |
| Qwen truncations | A faint mirrored invoice and a readable upside-down payment form | Both show repeated generated text, not merely a long legitimate transcription |
| Rotated and mixed-orientation scans | Several frozen normalized pages still contain 90/180-degree text | Normalization must be verified at the source boundary |

Initial Qwen inference requests took about 240 seconds in total. This is not
a hardware-normalized throughput comparison: engines use different models,
devices, layouts, and historical execution conditions.

Manual image inspection confirmed the repetitions do not correspond to rows
in the source. It also exposed handwritten values and faint mirrored text
that cannot safely be resolved by agreement between models. On a readable
mixed-orientation payment page, Qwen transcribes portions missing from GLM;
the outputs still disagree on some long numeric identifiers.

## Controlled orientation experiments

Three supplementary requests used the same renderer, source, prompt and
limits, changing only explicit page rotation. PDFs were never rewritten.

1. **Upside-down handwritten warranty, +180 degrees:** reran GLM and Qwen.
   GLM's output changes from bottom-to-top section order to the visible
   heading-to-footer order. GLM/Qwen sequence agreement rises from 15.3% to
   74.3%; bag agreement remains approximately 75%. This demonstrates an
   ordering improvement, not validated correction of handwritten dates,
   names or serial numbers, which remain inconsistent.
2. **Japanese receipt, +270 degrees:** reran GLM and Qwen. The corrected GLM
   output includes the visible final payable-total row missing from its
   unrotated output. Both still make transcription errors; even a negation
   in the printed explanatory text is not reliably preserved. Neither output
   should be treated as gold.
3. **Readable upside-down payment form, +180 degrees:** reran Qwen only.
   The original request repeats a bank word until `finish_reason=length`
   at 8192 tokens, taking approximately 83 seconds. The upright request
   terminates normally in approximately 6 seconds with 147 words; 27/29
   archived numeric occurrences match. This is a concrete orientation-sensitive
   failure, not proof that every loop has this cause. A repeated paired
   experiment is required before asserting deterministic causality.

Global page rotation cannot correct mixed-orientation pages, nor does it
remove bleed-through or decipher handwriting. Region-level layout and
orientation need separate evaluation.

## Reproducibility

Use `scripts/triage_ocr_qwen.py` in the API image with a read-only source-tree
mount and a writable evidence directory outside the repository. It requires
the frozen corpus layout produced by the earlier corpus experiment.

```bash
python scripts/triage_ocr_qwen.py \
  --corpus /evidence/2026-10-05-corpus-int8 \
  --output /evidence/new-qwen-triage \
  --endpoint http://host.docker.internal:18020/v1
```

`--prepare-only` records the selection without inference. `--case OCR_ID PAGE
ROTATION_DELTA` selects an explicit source page; rotations must be 0/90/180/270.
`--glm-endpoint http://host.docker.internal:18030/v1` also evaluates GLM on that
image. Use a new output directory when changing experiment configuration.
Attempted pages are checkpointed, including failed completions; resuming does
not silently retry them. HTTP errors stop execution.

`--report-only` recomputes `comparison.json` from saved raw responses without
running inference. It strips an outer HTML/Markdown code fence before scoring
so CSS attributes do not become false OCR words or numbers. Original responses
and their original manifest remain unchanged; the analysis code hash is stored
separately. Scores are concordance, never accuracy. Numeric matching still has
limitations around spacing, punctuation, dates and identifier grouping.

Private evidence locations on the experiment host:

- `~/megadoc-ocr-benchmarks/2026-10-05-qwen-triage/`
- `~/megadoc-ocr-benchmarks/2026-10-05-qwen-orientation/`
- `~/megadoc-ocr-benchmarks/2026-10-05-qwen-upside-down-loop/`

## Prioritized follow-up

1. Reject loops and token-limit completions for every OCR engine, not only
   GLM. Include explicit extraction-failure metadata and a review path; do not
   substitute another engine silently. Verify with the two saved Qwen failures
   and clean controls before enabling a guard in production.
2. Audit accepted historical dots output for repetitions. Flag suspect derived
   results without changing original files or automatically treating another
   model's output as a correction.
3. Evaluate normalization and region orientation against source images. Repeat
   the paired upside-down form experiment; measure both loop incidence and
   source-validated fields. Include mixed-angle pages and handwriting controls.
4. Separate ordering, omitted regions, character recognition and hallucinations
   in evaluation. Annotate a small source-checked set of critical cells, totals
   and dates; retain disagreement scores only as sampling tools.
5. Only then choose the production engine and preprocessing configuration.
   This adverse sample does not establish that GLM or Qwen is globally superior
   to dots, or isolate an OpenVINO-versus-other-runtime quality difference.

## Verification

Focused tests: 13 passed across triage selection/format handling and corpus
metrics. The script ran to completion in the API image without rebuilding
production services. Qwen and GLM remained available and only one Qwen instance
was active. The archive remained unchanged: 49 OCR results, combined checksum
`6004465a8613c4677eb3f80b464705fc`, identical to the pre-experiment snapshot.
