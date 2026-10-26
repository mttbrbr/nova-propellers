import assert from 'node:assert/strict';
import { chmod, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { chromium } from 'playwright';

const temporary = await mkdtemp(join(tmpdir(), 'nova-external-browser-'));
const browser = await chromium.launch({ executablePath: process.env.NOVA_CHROMIUM_PATH === 'managed' ? undefined : process.env.NOVA_CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const api = process.env.NOVA_API_TEST_URL || 'http://127.0.0.1:8777/api';
  const post = async (path, data) => {
    const response = await page.request.post(`${api}${path}`, { data });
    assert.ok(response.ok(), `${path}: ${response.status()} ${await response.text()}`);
    return response.json();
  };
  const source = Buffer.from('NOVA archive browser fixture\nTime GenPwr\n(s) (kW)\n0 10\n1 20\n');
  const imported = await post('/v1/openfast/import', { filename: 'portable.out', content_base64: source.toString('base64') });
  await page.goto(process.env.NOVA_UI_TEST_URL || 'http://127.0.0.1:5174');
  const navigation = page.getByRole('navigation', { name: 'Workspace navigation' });
  await navigation.getByRole('button', { name: 'Integrations', exact: true }).click();
  const history = page.getByRole('combobox', { name: 'Saved external run', exact: true });
  await history.locator(`option[value="${imported.id}"]`).waitFor({ state: 'attached' });
  await history.selectOption(imported.id);
  await page.getByRole('combobox', { name: 'OpenFAST output channel', exact: true }).waitFor();
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export external archive', exact: true }).click();
  const archive = await download;
  assert.ok(archive.suggestedFilename().endsWith('.nova-run'));
  const upload = page.waitForResponse((response) => response.url().endsWith('/external-runs/import') && response.request().method() === 'POST');
  await page.getByLabel('Open external archive', { exact: true }).setInputFiles({ name: archive.suggestedFilename(), mimeType: 'application/zip', buffer: await readFile(await archive.path()) });
  const restored = await (await upload).json();
  assert.notEqual(restored.id, imported.id);
  assert.equal(restored.imported_from_run, imported.id);
  assert.deepEqual(restored.result.data, imported.result.data);
  assert.equal(restored.external_job.operation, 'portable_import');
  assert.equal(restored.external_job.configuration, undefined);
  await page.getByText(`Portable result imported from run ${imported.id}.`, { exact: false }).waitFor();
  const raw = await page.request.get(`${api}/v1/external-runs/${restored.id}/artifacts/source/portable.out`);
  assert.deepEqual(await raw.body(), source);
  await navigation.getByRole('button', { name: 'Studies', exact: true }).click();
  await navigation.getByRole('button', { name: 'Integrations', exact: true }).click();
  await history.locator(`option[value="${restored.id}"]`).waitFor({ state: 'attached' });
  await history.selectOption(restored.id);
  await page.getByRole('img', { name: 'GenPwr versus time', exact: true }).waitFor();

  // This executable only exercises process lifecycle; it is not an OpenFAST solver.
  const fixture = join(temporary, 'openfast-process-fixture');
  await writeFile(fixture, '#!/usr/bin/env python3\nimport sys,time\nif sys.argv[1:] == ["-v"]:\n print("OpenFAST-v4.1.1")\nelse:\n print("fixture started", flush=True)\n time.sleep(30)\n');
  await chmod(fixture, 0o755);
  await writeFile(join(temporary, 'main.fst'), 'Process fixture input\n');
  const configuration = await post('/v1/adapters/openfast/configure', { executable: fixture, environment_kind: 'local_executable' });
  // Remount to refresh independently saved executable configurations.
  await navigation.getByRole('button', { name: 'Studies', exact: true }).click();
  await navigation.getByRole('button', { name: 'Integrations', exact: true }).click();
  await page.getByRole('combobox', { name: 'External adapter', exact: true }).selectOption('openfast');
  await page.getByRole('combobox', { name: 'Saved integration configuration', exact: true }).selectOption(configuration.id);
  await page.getByLabel('Case directory', { exact: true }).fill(temporary);
  await page.getByLabel('Input .fst file (relative to case)', { exact: true }).fill('main.fst');
  await page.getByLabel('Expected .out or .outb file (relative to case)', { exact: true }).fill('main.out');
  const submission = page.waitForResponse((response) => response.url().endsWith('/external-runs') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Run OpenFAST case', exact: true }).click();
  const queued = await (await submission).json();
  await page.getByRole('button', { name: 'Cancel', exact: true }).waitFor();
  await navigation.getByRole('button', { name: 'Studies', exact: true }).click();
  await page.getByRole('button', { name: 'Cancel', exact: true }).waitFor();
  await navigation.getByRole('button', { name: 'Integrations', exact: true }).click();
  await page.getByRole('heading', { name: /External run · (queued|running)/ }).waitFor();
  assert.equal(await page.getByRole('button', { name: /Cancel/ }).count(), 1);
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await page.getByRole('heading', { name: /External run · cancelled/ }).waitFor({ timeout: 20000 });
  const cancelled = await (await page.request.get(`${api}/v1/runs/${queued.id}`)).json();
  assert.equal(cancelled.state, 'cancelled');
  assert.deepEqual(errors, []);
  console.log('External archive export/import/source fidelity/reopen and persistent global execution cancellation passed (process fixture only).');
} finally {
  await browser.close();
  await rm(temporary, { recursive: true, force: true });
}
