# RotDet2 recovery and bounded Pi experiment plan

## Decision

Resume RotDet2 as a bounded independent experiment, not as a prerequisite
for Megadoc ingestion. The existing datasets and small-model checkpoints
justify a controlled trial. Do not commit to beating Paddle or reaching an
arbitrary validation threshold before a trustworthy evaluation exists.

The user confirms that the original Archive.org training images were upright.
Artificial quarter-turn labels are appropriate for that corpus. This does not
establish orientation labels for unrelated scans in the Megadoc archive.

## Inspected state, 2026-10-06

- Legacy workspace: `/mnt/data01/work/rotdet`, branch `rotdet2`, local commit
  `bb2714d`, ahead of its recorded tracking branch by one commit.
- There are tracked uncommitted changes in the May report, model registry,
  `c4net_v2.py`, TTA evaluator and training scripts, plus untracked work.
  They must be preserved, not replaced by the GitHub checkout.
- Approximately 19 GB of local data and 2.3 GB of checkpoints exist.
  ReaderService, Junkfaxes and a combined Hugging Face dataset are available.
- A saved 35-epoch summary records best validation accuracy 97.64% on 592
  validation pages, with roughly 60 seconds for its final epoch. The May
  report explicitly warns that validation rotations were stochastic and
  that duplicate training processes overwrote checkpoints. These figures
  are historical observations, not validated current performance claims.
- The local V2 orientation head averages across orientations before a linear
  classifier. It needs correction independently of the GitHub V1 layout bug.
- The installed Qwen uses about 23.5 GB of the 24 GB NVIDIA GPU. Do not start
  another Qwen or GPU training concurrently with that server.
- The functioning Pi example in `~/ocrServe` pins Pi 0.87.1, uses the existing
  vLLM endpoint and persistent agent/session directories, with loop-audit,
  procedure and compaction-recovery extensions. Reuse its agent configuration,
  not its Intel OCR-specific bootstrap or device requirements.

## Environment design

Create an independent lab, for example `~/rotdet-lab`, with a dedicated Git
worktree/repository, persistent Pi state and a private experiment directory.
Keep the legacy workspace read-only. Copy its current source state, including
uncommitted source edits, into the lab; record the base commit and original
diff. Inspect untracked files before inclusion. Do not copy session transcripts,
datasets, checkpoints or credentials into Git.

Use two separately constrained Compose services:

- `pi`: pinned Node/Pi environment using the existing Qwen endpoint at
  `host.docker.internal:18020/v1`; persistent sessions; no NVIDIA devices,
  Docker socket, home-directory mount or access to other project worktrees.
- `lab`: pinned Python/PyTorch CPU environment with dataset readers, safetensors
  and focused test dependencies. Separate optional Paddle evaluation dependencies
  if they materially enlarge the training environment.

Expose a narrow job submission mechanism through a shared job directory or
runner CLI rather than giving Pi host Docker control. Pi writes bounded job
specifications; a single runner executes validated commands and records state.
Use an OS lock, unique run directories and atomic checkpoint writes. Jobs
must not be arbitrary shell commands. Define allowed train/evaluate/test jobs,
path validation, limits and status before enabling autonomous execution.

Start with 4 CPU cores and 8 GB RAM for the lab, adapting batch size after a
memory smoke test; Pi gets a separate modest limit. No GPU devices are mapped
to either service. Mount legacy datasets read-only and preserve any absolute
image paths required by the HF snapshots. New outputs are isolated. Record
requested and actual execution device; never mislabel CPU as GPU.

## Steps and acceptance criteria

### 0. Preserve and inventory

Record source provenance, uncommitted diff, dependency lock, dataset schemas,
page/document counts, image-path availability, split identities and checkpoint
architecture metadata. Hash dataset manifests and baseline checkpoint files;
avoid repeatedly hashing all original PDFs during each experiment.

Acceptance: clean source rollback point in the lab, original workspace unchanged,
all selected dataset images resolvable from the container, and explicit baseline
checkpoint/model pairing. Old weights are not silently loaded into fixed models.

### 1. Repair mathematical and data contracts

Make C4 channel layout consistent across convolutions, reshape helpers and
pooling. Use four orientation scores without averaging away the orientation
axis. Check normalization parameters/statistics across group channels, stride
sampling-grid alignment, and optional SE/dropout effects on equivariance.
Disable optional components until their contracts are tested. Avoid a broad
architecture rewrite.

Fix worker partitioning, RNG ownership and document-level split leakage in any
active loader. Prefer existing local map-style snapshots if streaming is not
needed. Audit ReaderService document identifiers and use hashes where Junkfaxes
lacks an explicit document identity. Validate duplicates across combined sources.

Acceptance: deterministic tests for channel ordering, quarter-turn logit
permutation, actual PDF corrective-angle convention, all four labels, eval/train
normalization behavior, worker coverage without duplicates and split separation.
Test the full network, not only convolutions with stride one. A small synthetic
set must overfit before a full run. No large training starts with failing tests.

### 2. Freeze evaluation before tuning

Build a versioned manifest that evaluates every held-out upright page in all
four rotations. Split by original document before generating variants. Audit
existing splits; rebuild only the evaluation manifest if old splits leak.
Separate validation used for selection from a document-held-out test set.

Report per-angle confusion, macro accuracy, upright pages rotated incorrectly,
latency, memory and confidence/coverage curves. Empty or mixed-angle pages
belong to a separately annotated real-world set, not forced single-angle labels.
Do not claim an untouched public benchmark if local checkpoints already saw it.

Acceptance: repeated evaluation of an unchanged model yields identical sample
identities, labels and predictions on the pinned CPU environment. The test set
is never used for Pi's hyperparameter selection.

### 3. Reproduce baselines and measure feasibility

Evaluate one compatible historical checkpoint without changing its architecture,
the repaired model's initial state and Paddle on the same fixed validation
manifest. These are distinct model versions with explicit provenance. Measure
CPU epoch time and peak memory on a short training run; do not extrapolate solely
from the historical report.

Acceptance: complete comparable baseline reports and a justified training budget.
If a historical checkpoint cannot load reproducibly, document the incompatibility
rather than modifying it or declaring its old score reproduced.

### 4. Delegate a limited experiment to Pi/Qwen

Write `AGENTS.md`, `GOAL.md` and a machine-readable experiment matrix for the
lab. Pi may supervise jobs, analyze failures and propose narrow source changes.
It must commit coherent tested source slices, but must not merge/push changes,
touch Megadoc, alter legacy data, download new corpora or start another server.

Initial budget: one smoke training plus at most three sequential full candidate
runs, each capped at 60 epochs and two hours; six hours maximum full-training
time overall. Begin with the corrected simple orientation model and one corrected
residual V2. A third run is permitted only with a documented validation-based
hypothesis. No unbounded sweep or automatic relaunch on stalled progress.

The runner enforces budgets and locks independently of the agent. A restart
recovers recorded job state instead of launching duplicate work. Pi records
baseline, hypothesis, command, source SHA, seed, dataset manifest, actual device,
metrics and conclusion. Provide a heartbeat/status file and attachable sessions.

Acceptance: demonstrate restart/duplicate-submission handling and timeout behavior
with tiny jobs before starting training; only one training process owns any run;
source edits are tested before a new run. Agent-loop auditing is useful but not
a substitute for process-level protection.

### 5. Independent decision gate

Review Pi's changes and reproduce selected metrics outside its session. Select
the candidate on validation, then run the held-out test once. Compare errors
with Paddle on identical pages, including source-reviewed Megadoc regression
pages. Report paired wins/losses and document-level uncertainty where feasible,
not just a best epoch on random rotations.

Acceptance: select RotDet only if it provides a useful error/coverage or deployment
advantage over Paddle on the defined use case. Otherwise retain Paddle and archive
the experiment with its findings. A working tested training/evaluation project
is a valid outcome even if the model is not adopted by Megadoc.

### 6. Optional deployment, separate scope

Only after the decision gate, package a small inference dependency/service with
explicit angle semantics, versioned weights, confidence and abstention policy.
CPU is the first deployment target. OpenVINO export is optional and must be
checked against PyTorch predictions and real latency before choosing the iGPU.
Keep document order separate from physical rotation. Do not infer reversed page
order from a 180-degree prediction. No production switch belongs to this experiment.

## Current boundary

This document is a plan based on read-only inspection. No lab environment,
autonomous Pi session or new training has been started. No legacy files or
Megadoc pipeline settings have been changed.
