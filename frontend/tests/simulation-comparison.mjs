import assert from 'node:assert/strict';
import { mkdir, readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const browser = await chromium.launch({ executablePath: process.env.NOVA_CHROMIUM_PATH === 'managed' ? undefined : process.env.NOVA_CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const screenshots = new URL('../../.desktop-tools/ui-navigation/comparison-explorer/', import.meta.url);
  await mkdir(screenshots, { recursive: true });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const api = process.env.NOVA_API_TEST_URL || 'http://127.0.0.1:8777/api';
  const post = async (path, data) => {
    const response = await page.request.post(`${api}${path}`, { data });
    assert.ok(response.ok(), `${path}: ${response.status()} ${await response.text()}`);
    return response.json();
  };
  const inputs = { project_name: 'Guided solver comparison browser project', propeller_type: 'traditional', thrust_target: 10, rpm: 5000, diameter: 0.25, blades: 2, airfoil: 'NACA 4412', geometry_method: 'bezier', airfoil_assignments: [], geometry_parameters: {
    chord_points: [{ x: 0, y: .02625 }, { x: .32, y: .02875 }, { x: .72, y: .01625 }, { x: 1, y: .0045 }],
    twist_points: [{ x: 0, y: 34 }, { x: .33, y: 25 }, { x: .72, y: 14 }, { x: 1, y: 7 }],
  } };
  const workflow = await (await page.request.get(`${api}/v1/workflow-template`)).json();
  const polar = await post('/v1/assets/demonstration-polar', { airfoil: inputs.airfoil });
  const definition = { name: inputs.project_name, inputs, workflow, conditions: { air_density_kg_m3: 1.225, air_viscosity_pa_s: 1.81e-5 }, polar_asset_id: polar.id };
  const project = await post('/v1/projects', definition);
  const baseline = await post('/v1/simulations', { ...definition, name: 'BEMT reference', project_id: project.id, geometry_id: project.geometry_id, geometry_revision: project.geometry_revision });
  const lltWorkflow = { ...workflow, nodes: workflow.nodes.map((n) => n.type === 'analysis' ? { ...n, config: { ...n.config, model: 'llt' } } : n) };
  const lltDefinition = { ...definition, name: 'LLT comparison', project_id: project.id, workflow: lltWorkflow, geometry_id: project.geometry_id, geometry_revision: project.geometry_revision };
  const llt = await post('/v1/simulations', lltDefinition);
  await post('/v1/simulations', { ...lltDefinition, name: 'Mismatched RPM', inputs: { ...inputs, rpm: 6500 } });
  await page.goto(process.env.NOVA_UI_TEST_URL || 'http://127.0.0.1:5174');
  await page.getByRole('combobox', { name: 'Open saved project', exact: true }).selectOption(project.id);
  await page.getByRole('navigation', { name: 'Workspace navigation' }).getByRole('button', { name: 'Studies', exact: true }).click();
  const panel = page.getByRole('region', { name: 'Guided solver comparison', exact: true });
  await panel.getByRole('checkbox', { name: 'Compare simulation BEMT reference', exact: true }).check();
  await panel.getByRole('checkbox', { name: 'Compare simulation Mismatched RPM', exact: true }).check();
  await panel.getByRole('button', { name: 'Validate comparison', exact: true }).click();
  await panel.getByRole('alert').filter({ hasText: /matching RPM/ }).waitFor();
  assert.equal(await panel.getByRole('button', { name: 'Run solver comparison', exact: true }).isEnabled(), false);
  await panel.getByRole('checkbox', { name: 'Compare simulation Mismatched RPM', exact: true }).uncheck();
  await panel.getByRole('checkbox', { name: 'Compare simulation LLT comparison', exact: true }).check();
  await panel.getByRole('button', { name: 'Validate comparison', exact: true }).click();
  await panel.getByText('Compatible comparison · 2 frozen configuration revisions', { exact: true }).waitFor();
  // A stale selection must fail explicitly rather than running a newer saved revision.
  const revisedLlt = await post('/v1/simulations', { ...lltDefinition, id: llt.id, expected_revision: llt.revision });
  await panel.getByRole('button', { name: 'Validate comparison', exact: true }).click();
  await panel.getByRole('alert').filter({ hasText: /Revision conflict/ }).waitFor();
  assert.equal(await panel.getByRole('button', { name: 'Run solver comparison', exact: true }).isEnabled(), false);
  await panel.getByRole('button', { name: 'Refresh saved configurations', exact: true }).click();
  await panel.getByRole('row').filter({ has: page.getByRole('checkbox', { name: 'Compare simulation LLT comparison', exact: true }) }).getByText(`LLT comparison · r${revisedLlt.revision}`, { exact: false }).waitFor();
  await panel.getByRole('button', { name: 'Validate comparison', exact: true }).click();
  await panel.getByText('Compatible comparison · 2 frozen configuration revisions', { exact: true }).waitFor();
  const submission = page.waitForResponse((response) => response.url().endsWith(`/projects/${project.id}/comparisons`) && response.request().method() === 'POST');
  await panel.getByRole('button', { name: 'Run solver comparison', exact: true }).click();
  const queued = await (await submission).json();
  assert.ok(['queued', 'running'].includes(queued.state));
  assert.equal(queued.comparison.simulations[0].id, baseline.id);
  assert.equal(queued.comparison.simulations[1].revision, revisedLlt.revision);
  // Editing a source configuration after submission must not change the batch or its inspected result.
  await post('/v1/simulations', { ...lltDefinition, id: llt.id, expected_revision: revisedLlt.revision, inputs: { ...inputs, rpm: 6000 } });
  const table = panel.getByRole('table', { name: 'Solver comparison results', exact: true });
  await table.getByRole('button', { name: 'Inspect comparison LLT comparison', exact: true }).waitFor({ timeout: 30000 });
  await panel.getByText('2/2 comparison cases completed · 0 failed', { exact: true }).waitFor();
  assert.equal(await table.getByRole('row').count(), 3);
  await table.getByText('Reference', { exact: true }).waitFor();
  const csvDownload = page.waitForEvent('download');
  await panel.getByRole('button', { name: 'Export solver comparison CSV', exact: true }).click();
  const csv = await csvDownload;
  assert.equal(csv.suggestedFilename(), 'solver-comparison.csv');
  const csvText = await readFile(await csv.path(), 'utf8');
  assert.ok(csvText.includes('simulation_name') && csvText.includes('baseline_differences_pct') && csvText.includes('LLT comparison'));
  const persisted = await (await page.request.get(`${api}/v1/runs/${queued.id}`)).json();
  assert.equal(persisted.result.cases[1].snapshot.inputs.rpm, 5000);
  assert.equal(persisted.result.rows[1].simulation_revision, revisedLlt.revision);
  assert.equal(persisted.result.rows[0].baseline_differences_pct.thrust_n, 0);
  assert.equal(typeof persisted.result.rows[1].baseline_differences_pct.thrust_n, 'number');
  await table.scrollIntoViewIfNeeded();
  await page.screenshot({ path: fileURLToPath(new URL('solver-comparison-1440.png', screenshots)), animations: 'disabled' });
  await table.getByRole('button', { name: 'Inspect comparison LLT comparison', exact: true }).click();
  await page.getByText('Technical report', { exact: true }).waitFor();
  const context = page.locator('[aria-label="Project and simulation context"]');
  await context.getByText(new RegExp(`Viewing LLT comparison · r${revisedLlt.revision} · LLT · 5000 rpm`)).waitFor();
  assert.deepEqual(errors, []);
  console.log('Guided BEMT/LLT comparison: mismatch and revision conflict checks, queued frozen batch, normalized differences, CSV and exact-case inspection passed.');
} finally { await browser.close(); }
