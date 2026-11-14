import assert from 'node:assert/strict';
import { chromium } from 'playwright';

// The block settings card opens where there is room and never leaves the canvas.
const browser = await chromium.launch({ executablePath: process.env.NOVA_CHROMIUM_PATH === 'managed' ? undefined : process.env.NOVA_CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
try {
  for (const viewport of [{ width: 1920, height: 1080 }, { width: 1280, height: 720 }]) {
    const page = await browser.newPage({ viewport });
    await page.goto(process.env.NOVA_UI_TEST_URL || 'http://127.0.0.1:5174');
    await page.getByRole('navigation', { name: 'Workspaces' }).getByRole('button', { name: 'Workflow', exact: true }).click();
    const nodes = page.locator('.react-flow__node');
    await nodes.first().waitFor();
    await page.waitForTimeout(600);
    const count = await nodes.count();
    const sides = new Set();
    for (let pass = 0; pass < 2; pass += 1) {
      for (let i = 0; i < count; i += 1) {
        await page.keyboard.press('Escape');
        await nodes.nth(i).dispatchEvent('click'); // overlays may cover a block after zooming
        const card = page.getByRole('region', { name: 'Block settings' });
        await card.waitFor();
        await page.waitForTimeout(120);
        const canvas = await page.getByLabel('Block workflow canvas').boundingBox();
        const box = await card.boundingBox();
        const label = `${viewport.width}x${viewport.height} node ${i} pass ${pass}`;
        assert.ok(box.x >= canvas.x - 1 && box.y >= canvas.y - 1, `${label}: card starts outside the canvas (${JSON.stringify(box)})`);
        assert.ok(box.x + box.width <= canvas.x + canvas.width + 1 && box.y + box.height <= canvas.y + canvas.height + 1, `${label}: card ends outside the canvas (${JSON.stringify(box)} in ${JSON.stringify(canvas)})`);
        sides.add(await card.getAttribute('data-side'));
      }
      // Second pass: zoom in so blocks sit near and beyond the edges.
      if (pass === 0) {
        await page.keyboard.press('Escape');
        await page.getByRole('button', { name: 'Zoom in' }).click();
        await page.getByRole('button', { name: 'Zoom in' }).click();
        await page.waitForTimeout(300);
      }
    }
    console.log(`${viewport.width}x${viewport.height}: card sides used`, [...sides].join(', '));
    await page.close();
  }
  console.log('Block settings card placement passed');
} finally {
  await browser.close();
}
