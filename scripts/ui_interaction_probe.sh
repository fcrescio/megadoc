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

async function measure(label, action) {
  const started = performance.now();
  await action();
  return {
    label,
    duration_ms: Math.round((performance.now() - started) * 10) / 10,
  };
}

(async () => {
  const url = process.env.MEGADOC_PERF_URL;
  const timeout = Number(process.env.MEGADOC_PERF_TIMEOUT_MS || "30000");
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });

  await page.goto(url, { waitUntil: "networkidle", timeout });

  const results = [];
  for (const tab of ["Fatti", "Specialisti", "Topic", "Entità", "Revisioni", "Confronti"]) {
    results.push(await measure(`tab:${tab}`, async () => {
      await page.getByRole("button", { name: tab, exact: true }).click();
      await page.waitForTimeout(100);
    }));
  }

  const proposalsButton = page.getByRole("button", { name: /proposte/i }).first();
  if (await proposalsButton.count()) {
    results.push(await measure("modal:proposals", async () => {
      await proposalsButton.click();
      await page.getByText("Topic Proposals").waitFor({ timeout });
      await page.waitForTimeout(100);
    }));
  }

  const metrics = await page.evaluate(() => ({
    dom_nodes: document.querySelectorAll("*").length,
    body_text_sample: document.body.innerText.slice(0, 500),
  }));

  console.log(JSON.stringify({ url, results, metrics }, null, 2));
  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
EOF
    node probe.js
  '
