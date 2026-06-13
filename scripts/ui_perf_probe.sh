#!/usr/bin/env sh
set -eu

URL="${1:-http://127.0.0.1:3030/knowledge}"
IMAGE="${PLAYWRIGHT_IMAGE:-mcr.microsoft.com/playwright:v1.57.0-noble}"
TIMEOUT_MS="${UI_PERF_TIMEOUT_MS:-30000}"

docker run --rm --network host \
  -e PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
  -e PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
  -e MEGADOC_PERF_URL="$URL" \
  -e MEGADOC_PERF_TIMEOUT_MS="$TIMEOUT_MS" \
  "$IMAGE" sh -lc '
    set -eu
    mkdir -p /tmp/megadoc-playwright
    cd /tmp/megadoc-playwright
    npm init -y >/dev/null
    npm install --silent playwright@1.57.0
    cat > probe.js <<'"'"'EOF'"'"'
const { chromium } = require("playwright");

function simplifyTiming(timing) {
  return {
    request_start_ms: timing.requestStart,
    response_start_ms: timing.responseStart,
    response_end_ms: timing.responseEnd,
  };
}

(async () => {
  const url = process.env.MEGADOC_PERF_URL;
  const timeout = Number(process.env.MEGADOC_PERF_TIMEOUT_MS || "30000");
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const started = Date.now();
  const responses = [];

  page.on("response", (response) => {
    const responseUrl = response.url();
    if (!responseUrl.includes("/api/")) return;
    const request = response.request();
    responses.push({
      url: responseUrl,
      status: response.status(),
      method: request.method(),
      timing: simplifyTiming(request.timing()),
    });
  });

  await page.goto(url, { waitUntil: "networkidle", timeout });
  const metrics = await page.evaluate(() => {
    const nav = performance.getEntriesByType("navigation")[0]?.toJSON();
    const paint = performance.getEntriesByType("paint").map((entry) => entry.toJSON());
    const resources = performance.getEntriesByType("resource")
      .map((resource) => ({
        name: resource.name,
        duration_ms: Math.round(resource.duration * 10) / 10,
        transfer_size: resource.transferSize,
        initiator_type: resource.initiatorType,
      }))
      .sort((left, right) => right.duration_ms - left.duration_ms)
      .slice(0, 30);
    return {
      nav,
      paint,
      resources,
      body_text_sample: document.body.innerText.slice(0, 500),
    };
  });

  console.log(JSON.stringify({
    url,
    elapsed_ms: Date.now() - started,
    api_request_count: responses.length,
    api_responses: responses,
    metrics,
  }, null, 2));

  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
EOF
    node probe.js
  '
