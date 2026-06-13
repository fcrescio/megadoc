#!/usr/bin/env sh
set -eu

URL="${1:-http://127.0.0.1:3030/knowledge}"
OUT_DIR="${2:-tmp/ui-profiles}"
IMAGE="${PLAYWRIGHT_IMAGE:-mcr.microsoft.com/playwright:v1.57.0-noble}"
TIMEOUT_MS="${UI_PROFILE_TIMEOUT_MS:-30000}"
SETTLE_MS="${UI_PROFILE_SETTLE_MS:-1000}"

mkdir -p "$OUT_DIR"

docker run --rm --network host \
  -v "$PWD/$OUT_DIR":/profiles \
  -e PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
  -e PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
  -e MEGADOC_PROFILE_URL="$URL" \
  -e MEGADOC_PROFILE_TIMEOUT_MS="$TIMEOUT_MS" \
  -e MEGADOC_PROFILE_SETTLE_MS="$SETTLE_MS" \
  "$IMAGE" sh -lc '
    set -eu
    mkdir -p /tmp/megadoc-playwright
    cd /tmp/megadoc-playwright
    npm init -y >/dev/null
    npm install --silent playwright@1.57.0
    cat > profile.js <<'"'"'EOF'"'"'
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const categories = [
  "devtools.timeline",
  "disabled-by-default-devtools.timeline",
  "disabled-by-default-devtools.timeline.frame",
  "disabled-by-default-devtools.timeline.invalidationTracking",
  "disabled-by-default-devtools.timeline.layers",
  "blink",
  "blink.user_timing",
  "loading",
  "v8",
  "toplevel",
];

const renderEventNames = new Set([
  "BeginMainThreadFrame",
  "CompositeLayers",
  "DrawFrame",
  "HitTest",
  "InvalidateLayout",
  "Layout",
  "Paint",
  "PrePaint",
  "RecalculateStyles",
  "ScheduleStyleRecalculation",
  "UpdateLayerTree",
]);

function microsToMillis(value) {
  return Math.round((value / 1000) * 10) / 10;
}

function summarizeTrace(trace) {
  const totals = new Map();
  const longest = [];
  let eventCount = 0;

  for (const event of trace.traceEvents || []) {
    if (event.ph !== "X" || typeof event.dur !== "number") continue;
    eventCount += 1;
    const durationMs = event.dur / 1000;
    totals.set(event.name, (totals.get(event.name) || 0) + durationMs);
    if (renderEventNames.has(event.name) || durationMs >= 20) {
      longest.push({
        name: event.name,
        duration_ms: Math.round(durationMs * 10) / 10,
        category: event.cat,
      });
    }
  }

  longest.sort((left, right) => right.duration_ms - left.duration_ms);

  const topTotals = Array.from(totals.entries())
    .map(([name, duration]) => ({ name, total_ms: Math.round(duration * 10) / 10 }))
    .sort((left, right) => right.total_ms - left.total_ms)
    .slice(0, 25);

  const renderTotals = topTotals.filter((entry) => renderEventNames.has(entry.name));

  return {
    event_count: eventCount,
    top_totals: topTotals,
    render_totals: renderTotals,
    longest_render_or_long_tasks: longest.slice(0, 30),
  };
}

(async () => {
  const url = process.env.MEGADOC_PROFILE_URL;
  const timeout = Number(process.env.MEGADOC_PROFILE_TIMEOUT_MS || "30000");
  const settleMs = Number(process.env.MEGADOC_PROFILE_SETTLE_MS || "1000");
  const safeName = new URL(url).pathname.replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "") || "root";
  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  const tracePath = `/profiles/${timestamp}-${safeName}.trace.json`;
  const summaryPath = `/profiles/${timestamp}-${safeName}.summary.json`;

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();
  const client = await context.newCDPSession(page);

  await client.send("Tracing.start", {
    categories: categories.join(","),
    transferMode: "ReturnAsStream",
    options: "sampling-frequency=10000",
  });

  const started = Date.now();
  await page.goto(url, { waitUntil: "networkidle", timeout });
  await page.waitForTimeout(settleMs);

  const traceComplete = new Promise((resolve) => {
    client.once("Tracing.tracingComplete", resolve);
  });
  await client.send("Tracing.end");
  const { stream } = await traceComplete;

  let traceText = "";
  while (true) {
    const chunk = await client.send("IO.read", { handle: stream });
    traceText += chunk.data;
    if (chunk.eof) break;
  }
  await client.send("IO.close", { handle: stream });

  fs.writeFileSync(tracePath, traceText);
  const trace = JSON.parse(traceText);
  const summary = {
    url,
    elapsed_ms: Date.now() - started,
    settle_ms: settleMs,
    trace_path: tracePath,
    summary_path: summaryPath,
    ...summarizeTrace(trace),
  };
  fs.writeFileSync(summaryPath, JSON.stringify(summary, null, 2));
  console.log(JSON.stringify(summary, null, 2));

  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
EOF
    node profile.js
  '
