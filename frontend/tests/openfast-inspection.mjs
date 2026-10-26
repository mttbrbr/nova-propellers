import assert from 'node:assert/strict';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { chromium } from 'playwright';

const barrier = async (promise, label) => {
  let timer;
  try { await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`Timed out waiting for ${label}`)), 15000); })]); }
  finally { clearTimeout(timer); }
};
const directory = await mkdtemp(join(tmpdir(), 'nova-openfast-inspection-'));
const primary = '"sub/section.dat" AeroFile\n';
const section = 'Original case data\n';
await mkdir(join(directory, 'sub'));
await writeFile(join(directory, 'main.fst'), primary);
await writeFile(join(directory, 'sub', 'section.dat'), section);
const browser = await chromium.launch({ executablePath: process.env.NOVA_CHROMIUM_PATH === 'managed' ? undefined : process.env.NOVA_CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
let release;
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  let executableRequests = 0;
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('request', (request) => { if (request.method() === 'POST' && (/\/adapters\/openfast\/(probe|configure)$/.test(request.url()) || request.url().endsWith('/external-runs'))) executableRequests += 1; });
  await page.goto(process.env.NOVA_UI_TEST_URL || 'http://127.0.0.1:5174');
  await page.getByRole('navigation', { name: 'Workspace navigation' }).getByRole('button', { name: 'Integrations', exact: true }).click();
  await page.getByRole('combobox', { name: 'External adapter', exact: true }).selectOption('openfast');
  await page.getByRole('textbox', { name: 'Case directory', exact: true }).fill(directory);
  await page.getByRole('textbox', { name: 'Input .fst file (relative to case)', exact: true }).fill('main.fst');
  await page.getByRole('textbox', { name: 'Expected .out or .outb file (relative to case)', exact: true }).fill('main.out');
  const panel = page.getByRole('region', { name: 'OpenFAST case inspection', exact: true });
  const inspector = panel.getByRole('button', { name: 'Inspect OpenFAST case', exact: true });
  const firstResponse = page.waitForResponse((response) => response.url().endsWith('/v1/openfast/inspect') && response.request().method() === 'POST');
  await inspector.click();
  const first = await firstResponse;
  assert.equal(first.ok(), true, await first.text());
  const report = await first.json();
  assert.equal(report.file_count, 2);
  assert.equal(report.total_bytes, Buffer.byteLength(primary) + Buffer.byteLength(section));
  assert.match(report.case_hash, /^[a-f0-9]{64}$/);
  assert.deepEqual(report.input_files.map((file) => file.path).sort(), ['main.fst', 'sub/section.dat']);
  await panel.getByRole('status').filter({ hasText: 'Case inspected · 2 files' }).waitFor();
  await panel.getByText('Case file inventory', { exact: true }).click();
  const inventory = panel.getByRole('table', { name: 'OpenFAST input file inventory', exact: true });
  await inventory.getByRole('cell', { name: 'sub/section.dat', exact: true }).waitFor();
  assert.equal(await inventory.getByRole('row').count(), 3);
  await panel.getByText(`Snapshot SHA256: ${report.case_hash}`, { exact: true }).waitFor();
  await panel.getByText('Preflight does not execute OpenFAST or validate version-specific model settings.', { exact: true }).waitFor();
  await page.getByRole('textbox', { name: 'Input .fst file (relative to case)', exact: true }).fill('missing.fst');
  await panel.getByRole('status').filter({ hasText: 'Case not inspected for the current inputs.' }).waitFor();
  assert.equal(await panel.getByRole('table', { name: 'OpenFAST input file inventory', exact: true }).count(), 0);
  const invalidResponse = page.waitForResponse((response) => response.url().endsWith('/v1/openfast/inspect') && response.request().method() === 'POST');
  await inspector.click();
  assert.equal((await invalidResponse).status(), 422);
  await panel.getByRole('alert').filter({ hasText: 'Missing OpenFAST primary input' }).waitFor();
  await page.getByRole('textbox', { name: 'Input .fst file (relative to case)', exact: true }).fill('main.fst');
  let received;
  let fulfilled;
  const started = new Promise((resolve) => { received = resolve; });
  const finished = new Promise((resolve) => { fulfilled = resolve; });
  const hold = new Promise((resolve) => { release = resolve; });
  await page.route('**/api/v1/openfast/inspect', async (route) => {
    if (route.request().method() !== 'POST') return route.continue();
    const response = await route.fetch();
    received(); await hold;
    await route.fulfill({ response }); fulfilled();
  });
  await inspector.click();
  await barrier(started, 'the real inspection response');
  await panel.getByRole('button', { name: 'Inspecting case files…', exact: true }).waitFor();
  await page.getByRole('textbox', { name: 'Expected .out or .outb file (relative to case)', exact: true }).fill('main.outb');
  await panel.getByRole('status').filter({ hasText: 'Case not inspected for the current inputs.' }).waitFor();
  release(); await barrier(finished, 'the delayed response delivery');
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(resolve)));
  assert.equal(await panel.getByRole('table', { name: 'OpenFAST input file inventory', exact: true }).count(), 0, 'A stale inspection must not validate edited inputs');
  assert.equal(await panel.getByRole('alert').count(), 0);
  await page.unroute('**/api/v1/openfast/inspect');
  await inspector.click();
  await panel.getByRole('status').filter({ hasText: 'Case inspected · 2 files' }).waitFor();
  await panel.getByText('Input: main.fst · Expected output: main.outb', { exact: true }).waitFor();
  assert.equal(executableRequests, 0, 'Inspection must not probe, configure or run an executable');
  assert.deepEqual(errors, []);
  console.log('OpenFAST case inspection passed without a solver: real file inventory and hashes, missing-file errors, edited-input invalidation and stale-response rejection.');
} finally {
  release?.();
  await browser.close();
  await rm(directory, { recursive: true, force: true });
}
