import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const browser = await chromium.launch({ executablePath: process.env.NOVA_CHROMIUM_PATH === 'managed' ? undefined : process.env.NOVA_CHROMIUM_PATH || '/usr/bin/chromium',
  headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const projectAction = async (name) => {
    const control = page.getByRole('button', { name, exact: true });
    if (!await control.isVisible()) await page.getByText('Project actions', { exact: true }).click();
    await control.click();
  };
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto(process.env.NOVA_UI_TEST_URL || 'http://127.0.0.1:5174');
  await page.getByText('Project actions', { exact: true }).waitFor();
  await projectAction('New project');
  await page.getByRole('heading', { name: 'Initial sizing', exact: true }).waitFor();
  assert.equal(await page.getByRole('navigation', { name: 'Workspace navigation' }).locator('[aria-current="page"]').count(), 1);
  await page.getByRole('navigation', { name: 'Workspace navigation' }).getByRole('button', { name: 'Force analysis', exact: true }).click();
  await page.getByRole('button', { name: 'Use synthetic demonstration', exact: true }).click();
  await page.locator('select').filter({ has: page.locator('option:checked', { hasText: 'demonstration only' }) }).waitFor();
  await page.getByRole('button', { name: /Force analysis/ }).click();
  // Geometry generation remains a guided step.
  await page.getByRole('button', { name: /Geometry/ }).first().click();
  const generate = page.getByRole('button', { name: /Generate geometry/ });
  await generate.click();
  await page.getByRole('button', { name: /Force analysis/ }).click();
  await page.getByRole('button', { name: 'Run simulation', exact: true }).click();
  await page.getByRole('button', { name: 'Export CSV', exact: true }).waitFor({ timeout: 20000 });
  await page.getByRole('button', { name: /Workflow/ }).first().click();
  const editor = page.getByRole('region', { name: 'Workflow editor', exact: true });
  await editor.getByRole('heading', { name: 'Execution graph', exact: true }).waitFor();
  const canvasBounds = await editor.locator('[aria-label="Workflow canvas"]').boundingBox();
  assert.ok(canvasBounds.width > 700 && canvasBounds.height > 500, 'Workflow canvas must fill the main workspace');
  assert.equal(await page.getByRole('button', { name: 'Surface', exact: true }).count(), 0);
  await page.getByRole('button', { name: 'Customize workflow', exact: true }).click();
  await page.getByText('Add block', { exact: true }).waitFor();
  await page.getByRole('button', { name: 'Validate', exact: true }).click();
  await page.getByText('Valid · Guided compatible', { exact: true }).waitFor();
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  const projectId = await page.getByRole('combobox', { name: 'Open saved project' }).inputValue();
  assert.ok(projectId);
  const archive = page.waitForEvent('download');
  await projectAction('Export saved project .nova');
  assert.ok((await archive).suggestedFilename().endsWith('.nova'));
  await projectAction('New project');
  await page.getByRole('combobox', { name: 'Open saved project' }).selectOption(projectId);
  await page.getByRole('navigation', { name: 'Workspace navigation' }).getByRole('button', { name: 'Workflow', exact: true }).click();
  await page.getByText('Add block', { exact: true }).waitFor();
  await page.getByRole('button', { name: 'Studies', exact: true }).click();
  assert.equal(await page.getByRole('complementary', { name: 'Project controls' }).count(), 0);
  await page.getByRole('textbox', { name: 'Sweep values', exact: true }).fill('3500, 4250, 5000');
  await page.getByRole('button', { name: 'Run sweep', exact: true }).click();
  await page.getByText('3/3 completed · 0 failed', { exact: true }).waitFor({ timeout: 20000 });
  assert.equal(await page.getByRole('button', { name: 'Inspect', exact: true }).count(), 3);
  // The final checkpoint is visible before the stored-run list refresh ends.
  // Wait for both records before using their positions for selection.
  await page.getByRole('checkbox', { name: /Compare run/ }).nth(1).waitFor();
  const labels = await page.getByRole('checkbox', { name: /Compare run/ }).evaluateAll((nodes) => nodes.slice(0, 2).map((n) => n.getAttribute('aria-label')));
  const firstRun = page.getByRole('checkbox', { name: labels[0], exact: true });
  const secondRun = page.getByRole('checkbox', { name: labels[1], exact: true });
  await firstRun.check();
  await secondRun.check();
  const compare = page.getByRole('button', { name: 'Compare selected runs', exact: true });
  assert.equal(await compare.isEnabled(), true);
  await firstRun.uncheck();
  assert.equal(await compare.isEnabled(), false);
  await firstRun.check();
  await page.getByRole('button', { name: 'Compare selected runs', exact: true }).click();
  await page.getByRole('table', { name: 'Stored run comparison results', exact: true }).waitFor();
  const csvDownload = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export study CSV', exact: true }).click();
  assert.equal((await csvDownload).suggestedFilename(), 'study.csv');
  await page.getByRole('button', { name: 'Inspect', exact: true }).first().click();
  await page.getByText('Technical report', { exact: true }).waitFor();
  await page.getByRole('button', { name: 'Integrations', exact: true }).click();
  await page.getByRole('combobox', { name: 'External adapter', exact: true }).locator('option', { hasText: 'PyWake' }).waitFor({ state: 'attached' });
  await page.getByRole('combobox', { name: 'External adapter', exact: true }).selectOption('pywake');
  await page.getByLabel('Python environment interpreter', { exact: true }).waitFor();
  assert.equal(await page.getByRole('combobox', { name: 'Execution environment', exact: true }).inputValue(), 'python_environment');
  await page.getByRole('combobox', { name: 'External adapter', exact: true }).selectOption('openfast');
  await page.getByLabel('Solver executable', { exact: true }).waitFor();
  assert.equal(await page.getByRole('combobox', { name: 'Execution environment', exact: true }).inputValue(), 'local_executable');
  await page.getByLabel('Import OpenFAST output', { exact: true }).setInputFiles({ name: 'browser-import.out', mimeType: 'text/plain',
    buffer: Buffer.from('NOVA OpenFAST import test\n\nTime RotSpeed GenPwr\n(s) (rpm) (kW)\n0 10 100\n1 11 110\n2 12 120\n') });
  await page.getByRole('combobox', { name: 'OpenFAST output channel', exact: true }).waitFor({ timeout: 20000 });
  await page.getByRole('combobox', { name: 'OpenFAST output channel', exact: true }).selectOption('GenPwr');
  await page.getByRole('img', { name: 'GenPwr versus time', exact: true }).waitFor();
  await page.getByText('Minimum: 100 (kW)', { exact: true }).waitFor();
  const externalDownload = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export external CSV', exact: true }).click();
  assert.equal((await externalDownload).suggestedFilename(), 'openfast-results.csv');
  const importedId = await page.getByRole('combobox', { name: 'Saved external run', exact: true }).inputValue();
  assert.ok(importedId);
  await page.getByRole('button', { name: 'Studies', exact: true }).click();
  await page.getByRole('button', { name: 'Integrations', exact: true }).click();
  await page.getByRole('combobox', { name: 'Saved external run', exact: true }).locator(`option[value="${importedId}"]`).waitFor({ state: 'attached' });
  await page.getByRole('combobox', { name: 'Saved external run', exact: true }).selectOption(importedId);
  await page.getByRole('combobox', { name: 'OpenFAST output channel', exact: true }).waitFor();
  if (process.env.NOVA_PYWAKE_PYTHON) {
    await page.getByRole('combobox', { name: 'External adapter', exact: true }).selectOption('pywake');
    await page.getByLabel('Python environment interpreter', { exact: true }).fill(process.env.NOVA_PYWAKE_PYTHON);
    await page.getByRole('button', { name: 'Save configuration', exact: true }).click();
    await page.getByText(/Detected · Compatible/).waitFor({ timeout: 20000 });
    await page.getByRole('button', { name: 'Run PyWake case', exact: true }).click();
    await page.getByRole('heading', { name: 'Wind farm performance', exact: true }).waitFor({ timeout: 60000 });
    const pywakeDownload = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Export external CSV', exact: true }).click();
    assert.equal((await pywakeDownload).suggestedFilename(), 'pywake-results.csv');
    const pywakeId = await page.getByRole('combobox', { name: 'Saved external run', exact: true }).inputValue();
    assert.ok(pywakeId);
    await page.getByRole('button', { name: 'Studies', exact: true }).click();
    await page.getByRole('button', { name: 'Integrations', exact: true }).click();
    await page.getByRole('combobox', { name: 'Saved external run', exact: true }).locator(`option[value="${pywakeId}"]`).waitFor({ state: 'attached' });
    await page.getByRole('combobox', { name: 'Saved external run', exact: true }).selectOption(pywakeId);
    await page.getByRole('heading', { name: 'Wind farm performance', exact: true }).waitFor();
  }
  assert.deepEqual(errors, []);
  console.log('Guided workflow, studies, comparison, case inspection, integrations and exports passed.');
} finally {
  await browser.close();
}
