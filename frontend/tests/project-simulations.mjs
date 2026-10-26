import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const barrier = async (promise, label) => {
  let timer;
  try {
    await Promise.race([promise, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(`Timed out waiting for ${label}`)), 15000);
    })]);
  } finally { clearTimeout(timer); }
};

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
  const navigation = page.getByRole('navigation', { name: 'Workspace navigation' });
  const context = page.locator('[aria-label="Project and simulation context"]');
  await projectAction('New project');
  await context.getByText('No project open · unsaved propeller draft', { exact: true }).waitFor();
  await page.getByLabel('Project name', { exact: true }).fill('Multiple simulation browser project');
  await navigation.getByRole('button', { name: 'Force analysis', exact: true }).click();
  await page.getByRole('button', { name: 'Use synthetic demonstration', exact: true }).click();
  await page.locator('select').filter({ has: page.locator('option:checked', { hasText: 'demonstration only' }) }).waitFor();
  await page.getByRole('textbox', { name: 'Simulation name', exact: true }).fill('BEMT baseline');
  await page.getByRole('button', { name: 'Run simulation', exact: true }).click();
  await page.getByRole('button', { name: 'Export CSV', exact: true }).waitFor({ timeout: 30000 });
  const projectId = await page.getByRole('combobox', { name: 'Open saved project' }).inputValue();
  const baselineId = await page.getByRole('combobox', { name: 'Open saved simulation' }).inputValue();
  assert.ok(projectId && baselineId);
  await context.getByText('Simulation · saved', { exact: true }).waitFor();
  const executions = page.getByRole('button', { name: /^View execution / });
  await executions.first().waitFor();
  assert.equal(await executions.count(), 1);
  const firstRunLabel = await executions.first().getAttribute('aria-label');
  await page.getByRole('button', { name: 'Run simulation', exact: true }).click();
  await executions.nth(1).waitFor({ timeout: 30000 });
  assert.equal(await page.getByRole('combobox', { name: 'Open saved simulation' }).inputValue(), baselineId);
  await page.getByRole('button', { name: 'New simulation', exact: true }).click();
  await page.getByRole('textbox', { name: 'Simulation name', exact: true }).fill('LLT 6500');
  await page.getByLabel('Model', { exact: true }).selectOption('llt');
  await context.getByText('LLT', { exact: true }).waitFor();
  await navigation.getByRole('button', { name: 'Geometry', exact: true }).click();
  await page.getByLabel('Design RPM', { exact: true }).fill('6500');
  await navigation.getByRole('button', { name: 'Force analysis', exact: true }).click();
  await page.getByRole('button', { name: 'Run simulation', exact: true }).click();
  await executions.nth(2).waitFor({ timeout: 30000 });
  const comparisonId = await page.getByRole('combobox', { name: 'Open saved simulation' }).inputValue();
  assert.notEqual(comparisonId, baselineId);
  assert.equal(await page.getByRole('combobox', { name: 'Open saved project' }).inputValue(), projectId);
  await page.getByRole('combobox', { name: 'Open saved simulation' }).selectOption(baselineId);
  await context.getByText('BEMT', { exact: true }).waitFor();
  await context.getByText('Simulation · saved', { exact: true }).waitFor();
  assert.equal(await page.getByLabel('Model', { exact: true }).inputValue(), 'bemt');
  await page.getByLabel('Model', { exact: true }).selectOption('llt');
  await context.getByText('Simulation · unsaved changes', { exact: true }).waitFor();
  await page.getByRole('button', { name: 'Duplicate simulation', exact: true }).click();
  await context.getByText('Simulation · saved', { exact: true }).waitFor();
  await page.getByRole('combobox', { name: 'Open saved simulation' }).locator('option:checked').filter({ hasText: 'BEMT baseline copy' }).waitFor({ state: 'attached' });
  const cloneId = await page.getByRole('combobox', { name: 'Open saved simulation' }).inputValue();
  assert.notEqual(cloneId, baselineId);
  await page.getByRole('button', { name: firstRunLabel, exact: true }).click();
  await page.getByText('Technical report', { exact: true }).waitFor();
  await context.getByText(/Viewing BEMT baseline · r1 · BEMT · 5000 rpm/).waitFor();
  await context.getByText('LLT', { exact: true }).waitFor();
  await projectAction('Close project');
  await context.getByText('No project open · unsaved propeller draft', { exact: true }).waitFor();
  await page.getByRole('combobox', { name: 'Open saved project' }).selectOption(projectId);
  await page.getByRole('combobox', { name: 'Open saved simulation' }).locator(`option[value="${cloneId}"]`).waitFor({ state: 'attached' });
  await context.getByText('Simulation · saved', { exact: true }).waitFor();
  const configurations = await (await page.request.get(`http://127.0.0.1:8777/api/v1/projects/${projectId}/simulations`)).json();
  assert.equal(configurations.length, 3);
  const baseline = configurations.find((s) => s.id === baselineId);
  assert.equal(baseline.workflow.nodes.find((n) => n.type === 'analysis').config.model, 'bemt');
  assert.equal(baseline.inputs.rpm, 5000);
  assert.equal(baseline.revision, 1);
  // Publishing is explicit and cannot silently revise sibling configurations or old runs.
  await navigation.getByRole('button', { name: 'Geometry', exact: true }).click();
  const originalGeometry = baseline.geometry_revision;
  await page.getByLabel('Diameter', { exact: true }).fill('0.27');
  await context.getByText('Simulation · unsaved changes', { exact: true }).waitFor();
  await page.getByRole('button', { name: 'Publish geometry revision', exact: true }).click();
  await page.getByText(/Published geometry r/).waitFor();
  const beforeAdoption = await (await page.request.get(`http://127.0.0.1:8777/api/v1/projects/${projectId}/simulations`)).json();
  assert.equal(beforeAdoption.find((item) => item.id === baselineId).geometry_revision, originalGeometry);
  assert.equal(beforeAdoption.find((item) => item.id === cloneId).geometry_revision, originalGeometry);
  await page.getByText('Apply revision to saved simulations', { exact: true }).click();
  await page.getByRole('checkbox', { name: 'Adopt geometry for BEMT baseline', exact: true }).check();
  await page.getByRole('button', { name: 'Apply to selected simulations', exact: true }).click();
  await page.getByText('Selected simulations adopted this geometry revision. Historical executions remain unchanged.', { exact: true }).waitFor();
  const adopted = await (await page.request.get(`http://127.0.0.1:8777/api/v1/projects/${projectId}/simulations`)).json();
  assert.equal(adopted.find((item) => item.id === baselineId).geometry_revision, originalGeometry + 1);
  assert.equal(adopted.find((item) => item.id === baselineId).inputs.diameter, 0.27);
  assert.equal(adopted.find((item) => item.id === cloneId).geometry_revision, originalGeometry);
  const oldRun = await (await page.request.get(`http://127.0.0.1:8777/api/v1/runs/${firstRunLabel.replace('View execution ', '')}`)).json();
  assert.equal(oldRun.geometry_revision, originalGeometry);
  assert.equal(oldRun.result.geometry.diameter_m, 0.25);
  // Switching a dirty draft requires a deliberate discard or save decision.
  await page.getByRole('combobox', { name: 'Open saved simulation' }).selectOption(baselineId);
  await page.getByRole('dialog', { name: 'Unsaved simulation changes' }).waitFor();
  await page.getByRole('button', { name: 'Keep editing', exact: true }).click();
  assert.equal(await page.getByRole('combobox', { name: 'Open saved simulation' }).inputValue(), cloneId);
  await page.getByRole('combobox', { name: 'Open saved simulation' }).selectOption(baselineId);
  await page.getByRole('button', { name: 'Discard changes', exact: true }).click();
  await context.getByText('Simulation · saved', { exact: true }).waitFor();
  assert.equal(await page.getByLabel('Diameter', { exact: true }).inputValue(), '0.27');
  await page.getByRole('combobox', { name: 'Open saved simulation' }).selectOption(cloneId);
  await context.getByText('Simulation · saved', { exact: true }).waitFor();
  await page.waitForFunction(() => document.querySelector('input[aria-label="Diameter"]')?.value === '0.25');
  // One global Save publishes changed geometry only for the current simulation.
  await page.getByLabel('Diameter', { exact: true }).fill('0.26');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await page.getByText(/published geometry r.*for this simulation only/).waitFor();
  await context.getByText('Simulation · saved', { exact: true }).waitFor();
  const afterSave = await (await page.request.get(`http://127.0.0.1:8777/api/v1/projects/${projectId}/simulations`)).json();
  assert.equal(afterSave.find((item) => item.id === cloneId).inputs.diameter, 0.26);
  assert.equal(afterSave.find((item) => item.id === cloneId).geometry_revision, originalGeometry + 2);
  assert.equal(afterSave.find((item) => item.id === baselineId).geometry_revision, originalGeometry + 1);
  assert.equal(afterSave.find((item) => item.id === comparisonId).geometry_revision, originalGeometry);
  const stillOld = await (await page.request.get(`http://127.0.0.1:8777/api/v1/runs/${firstRunLabel.replace('View execution ', '')}`)).json();
  assert.equal(stillOld.result.geometry.diameter_m, 0.25);
  // Duplicate includes unsaved geometry edits without replacing its saved source.
  await page.getByLabel('Diameter', { exact: true }).fill('0.28');
  await page.getByRole('button', { name: 'Duplicate simulation', exact: true }).click();
  await page.getByText('Independent simulation copy created', { exact: true }).waitFor();
  await context.getByText('Simulation · saved', { exact: true }).waitFor();
  const geometryCopyId = await page.getByRole('combobox', { name: 'Open saved simulation' }).inputValue();
  assert.notEqual(geometryCopyId, cloneId);
  const afterCopy = await (await page.request.get(`http://127.0.0.1:8777/api/v1/projects/${projectId}/simulations`)).json();
  assert.equal(afterCopy.find((item) => item.id === geometryCopyId).inputs.diameter, 0.28);
  assert.equal(afterCopy.find((item) => item.id === cloneId).inputs.diameter, 0.26);
  assert.equal(afterCopy.find((item) => item.id === baselineId).geometry_revision, originalGeometry + 1);
  // Main commands are unique and reachable at desktop and narrow viewport widths.
  for (const width of [1440, 1024, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    const saveControl = page.getByRole('button', { name: 'Save', exact: true });
    const runControl = page.getByRole('button', { name: 'Run simulation', exact: true });
    assert.equal(await saveControl.count(), 1);
    assert.equal(await runControl.count(), 1);
    for (const control of [saveControl, runControl, page.getByText('Project actions', { exact: true })]) {
      const bounds = await control.boundingBox();
      assert.ok(bounds && bounds.x >= 0 && bounds.x + bounds.width <= width + 1, `Global command must fit ${width}px`);
    }
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `No horizontal overflow at ${width}px`);
    await page.screenshot({ path: `/tmp/nova-geometry-${width}.png`, fullPage: true, animations: 'disabled' });
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await navigation.getByRole('button', { name: 'Workflow', exact: true }).click();
  await navigation.locator('[aria-current="page"]').filter({ hasText: 'Workflow' }).waitFor();
  await page.getByRole('complementary', { name: 'Project controls' }).evaluate((panel) => { panel.scrollTop = 0; });
  await page.screenshot({ path: '/tmp/nova-workflow-1440.png', animations: 'disabled' });
  const other = await (await page.request.post('http://127.0.0.1:8777/api/v1/projects', { data: {
    name: 'Other project scope', inputs: baseline.inputs, workflow: baseline.workflow,
    conditions: baseline.conditions, polar_asset_id: baseline.polar_asset_id,
  } })).json();
  await page.reload();
  await page.getByRole('combobox', { name: 'Open saved project' }).selectOption(projectId);
  await context.getByText('Simulation · saved', { exact: true }).waitFor();
  await navigation.getByRole('button', { name: 'Studies', exact: true }).click();
  let release;
  let received;
  const hold = new Promise((resolve) => { release = resolve; });
  const started = new Promise((resolve) => { received = resolve; });
  await page.route('**/api/v1/simulations/*/study', async (route) => {
    const response = await route.fetch();
    received(); await hold;
    await route.fulfill({ response });
  });
  await page.getByRole('button', { name: 'Run sweep', exact: true }).click();
  await barrier(started, 'study submission');
  await page.getByRole('combobox', { name: 'Open saved project' }).selectOption(other.id);
  release();
  await page.getByRole('textbox', { name: 'Sweep values', exact: true }).waitFor();
  await page.waitForFunction((id) => document.querySelector('[aria-label="Open saved project"]')?.value === id, other.id);
  await page.waitForFunction(() => ![...document.querySelectorAll('button')].find((button) => button.textContent === 'Run sweep')?.disabled);
  assert.equal(await page.getByText(/^Study from /).count(), 0, 'An old-project study must not populate the new project');
  await page.unroute('**/api/v1/simulations/*/study');
  // Hold a returned job in the running UI state to verify cancellation without timing dependence.
  let delayedRun;
  let cancelRequested = false;
  let verifyOtherScope = false;
  let confirmOtherScopePoll;
  const otherScopePolled = new Promise((resolve) => { confirmOtherScopePoll = resolve; });
  await page.route('**/api/v1/simulations/*/study', async (route) => {
    const response = await route.fetch();
    delayedRun = await response.json();
    await route.fulfill({ response, json: { ...delayedRun, state: 'running', result: null, progress: 0.25 } });
  });
  await page.route('**/api/v1/runs/*', async (route) => {
    if (!delayedRun || !route.request().url().endsWith(`/runs/${delayedRun.id}`)) return route.continue();
    const response = await route.fetch();
    if (verifyOtherScope) confirmOtherScopePoll();
    if (cancelRequested) return route.fulfill({ response });
    await route.fulfill({ response, json: { ...delayedRun, state: 'running', result: null, progress: 0.25 } });
  });
  await page.route('**/api/v1/runs/*/cancel', async (route) => {
    assert.ok(route.request().url().endsWith(`/runs/${delayedRun.id}/cancel`));
    cancelRequested = true;
    const response = await route.fetch();
    await route.fulfill({ response });
  });
  await page.getByRole('button', { name: 'Run sweep', exact: true }).click();
  await page.getByRole('button', { name: 'Cancel', exact: true }).waitFor();
  await navigation.getByRole('button', { name: 'Workflow', exact: true }).click();
  assert.equal(await page.getByRole('button', { name: 'Cancel', exact: true }).count(), 1);
  assert.equal(await page.getByRole('button', { name: 'Cancel study', exact: true }).count(), 0);
  await page.getByRole('combobox', { name: 'Open saved project' }).selectOption(projectId);
  await navigation.getByRole('button', { name: 'Studies', exact: true }).click();
  verifyOtherScope = true;
  await barrier(otherScopePolled, 'study polling after project switch');
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await page.getByRole('button', { name: 'Run simulation', exact: true }).waitFor();
  assert.equal(cancelRequested, true, 'A study must remain cancellable after leaving its workspace and changing project');
  assert.deepEqual(errors, []);
  console.log('Project context, three independent configurations, repeated runs, model coherence, historical results and reopen passed.');
} finally { await browser.close(); }
