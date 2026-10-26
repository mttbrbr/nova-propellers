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
  const inputs = { project_name: 'Two-axis study browser project', propeller_type: 'traditional', thrust_target: 10, rpm: 5000, diameter: .25, blades: 2, airfoil: 'NACA 4412', geometry_method: 'bezier', airfoil_assignments: [], geometry_parameters: {
    chord_points: [{ x: 0, y: .02625 }, { x: .32, y: .02875 }, { x: .72, y: .01625 }, { x: 1, y: .0045 }],
    twist_points: [{ x: 0, y: 34 }, { x: .33, y: 25 }, { x: .72, y: 14 }, { x: 1, y: 7 }],
  } };
  const template = await (await page.request.get(`${api}/v1/workflow-template`)).json();
  const workflow = { ...template, nodes: template.nodes.map((n) => n.type === 'analysis' ? { ...n, config: { ...n.config, model: 'llt' } } : n) };
  const definition = { name: inputs.project_name, inputs, workflow, conditions: { air_density_kg_m3: 1.225, air_viscosity_pa_s: 1.81e-5 } };
  const project = await post('/v1/projects', definition);
  const simulation = await post('/v1/simulations', { ...definition, name: 'LLT grid baseline', project_id: project.id, geometry_id: project.geometry_id, geometry_revision: project.geometry_revision });
  await page.goto(process.env.NOVA_UI_TEST_URL || 'http://127.0.0.1:5174');
  await page.getByRole('combobox', { name: 'Open saved project', exact: true }).selectOption(project.id);
  const context = page.locator('[aria-label="Project and simulation context"]');
  await context.getByText('Simulation · saved', { exact: true }).waitFor();
  await page.getByRole('navigation', { name: 'Workspace navigation' }).getByRole('button', { name: 'Studies', exact: true }).click();
  assert.equal(await page.getByRole('checkbox', { name: 'Use second sweep axis', exact: true }).isChecked(), false);
  assert.equal(await page.getByRole('combobox', { name: 'Second sweep parameter', exact: true }).count(), 0);
  await page.getByRole('textbox', { name: 'Sweep values', exact: true }).fill('4000, 5000');
  await page.getByRole('checkbox', { name: 'Use second sweep axis', exact: true }).check();
  await page.getByRole('combobox', { name: 'Second sweep parameter', exact: true }).selectOption('air_density_kg_m3');
  await page.getByRole('textbox', { name: 'Second sweep values', exact: true }).fill('1.1, 1.225');
  const primaryDisabled = await page.getByRole('combobox', { name: 'Second sweep parameter', exact: true }).locator('option[value="rpm"]').evaluate((option) => option.disabled);
  assert.equal(primaryDisabled, true);
  const submission = page.waitForResponse((response) => response.url().endsWith(`/simulations/${simulation.id}/study`) && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Run sweep', exact: true }).click();
  const queued = await (await submission).json();
  assert.ok(['queued', 'running'].includes(queued.state));
  assert.deepEqual(queued.study.secondary, { parameter: 'air_density_kg_m3', values: [1.1, 1.225] });
  // The mutable configuration can change while every executed grid cell keeps its frozen values.
  await post('/v1/simulations', { ...definition, id: simulation.id, expected_revision: simulation.revision, name: simulation.name, project_id: project.id,
    geometry_id: project.geometry_id, geometry_revision: project.geometry_revision, inputs: { ...inputs, rpm: 6000 }, conditions: { ...definition.conditions, air_density_kg_m3: 1.0 } });
  await page.getByText('4/4 completed · 0 failed', { exact: true }).waitFor({ timeout: 30000 });
  const grid = page.getByRole('region', { name: 'Two-axis study grid', exact: true });
  const matrix = grid.getByRole('table', { name: 'Two-axis performance grid', exact: true });
  await grid.getByRole('button', { name: 'Inspect grid case 4', exact: true }).waitFor();
  assert.equal(await matrix.getByRole('row').count(), 3);
  assert.equal(await grid.getByRole('button', { name: /^Inspect grid case / }).count(), 4);
  assert.equal(await page.getByRole('img', { name: 'Thrust versus sweep parameter', exact: true }).count(), 0, 'A Cartesian grid must not connect repeated primary-axis points');
  const normalized = await (await page.request.get(`${api}/v1/runs/${queued.id}/study.rows`)).json();
  assert.deepEqual(normalized.axes.map((axis) => axis.parameter), ['rpm', 'air_density_kg_m3']);
  assert.equal(normalized.rows.length, 4);
  assert.deepEqual(normalized.rows.map((row) => [row.value, row.secondary_value]), [[4000, 1.1], [4000, 1.225], [5000, 1.1], [5000, 1.225]]);
  await matrix.getByRole('columnheader', { name: `1.225 [${normalized.axes[1].units}]`, exact: true }).waitFor();
  assert.equal(await page.getByRole('table', { name: 'Sweep results', exact: true }).getByRole('row').count(), 5);
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export study CSV', exact: true }).click();
  const csv = await download;
  assert.equal(csv.suggestedFilename(), 'study.csv');
  const csvText = await readFile(await csv.path(), 'utf8');
  assert.ok(csvText.includes('secondary_parameter') && csvText.includes('secondary_units') && csvText.includes('secondary_value'));
  const persisted = await (await page.request.get(`${api}/v1/runs/${queued.id}`)).json();
  assert.deepEqual(persisted.result.cases.map((sample) => [sample.inputs.rpm, sample.conditions.air_density_kg_m3]), [[4000, 1.1], [4000, 1.225], [5000, 1.1], [5000, 1.225]]);
  for (const width of [1440, 1024, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    await grid.scrollIntoViewIfNeeded();
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `Two-axis workspace must fit ${width}px`);
    await page.screenshot({ path: fileURLToPath(new URL(`two-axis-${width}.png`, screenshots)), animations: 'disabled' });
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  const snapshotGeometry = page.waitForResponse((response) => response.url().endsWith(`/runs/${queued.id}/cases/3/stl`) && response.request().method() === 'GET');
  await grid.getByRole('button', { name: 'Inspect grid case 4', exact: true }).click();
  await page.getByText('Technical report', { exact: true }).waitFor();
  await context.getByText(/Viewing LLT grid baseline.*5000 rpm/).waitFor();
  await context.getByText(/air_density_kg_m3.*1\.225/).waitFor();
  const geometryResponse = await snapshotGeometry;
  assert.equal(geometryResponse.ok(), true);
  assert.ok(geometryResponse.headers()['content-type']?.includes('model/stl'));
  const exactGeometry = await page.request.get(`${api}/v1/runs/${queued.id}/cases/3/stl`);
  assert.equal(exactGeometry.ok(), true);
  assert.ok((await exactGeometry.body()).length > 84);
  const explorer = page.locator('[aria-label="Project explorer"]');
  await explorer.getByRole('textbox', { name: 'Search project explorer', exact: true }).fill('LLT grid baseline');
  await explorer.getByRole('button', { name: 'Open simulation LLT grid baseline', exact: true }).waitFor();
  await explorer.getByRole('button', { name: `View execution ${queued.id}`, exact: true }).waitFor();
  // The tree opens the current source configuration independently from its earlier frozen study.
  await explorer.getByRole('button', { name: 'Open simulation LLT grid baseline', exact: true }).click();
  await context.getByText('Simulation · saved', { exact: true }).waitFor();
  await explorer.getByRole('button', { name: `View execution ${queued.id}`, exact: true }).click();
  await page.getByRole('region', { name: 'Two-axis study grid', exact: true }).getByRole('button', { name: 'Inspect grid case 4', exact: true }).waitFor();
  assert.equal(await page.getByRole('region', { name: 'Two-axis study grid', exact: true }).getByRole('button', { name: /^Inspect grid case / }).count(), 4);
  await page.getByRole('navigation', { name: 'Workspace navigation' }).getByRole('button', { name: 'Workflow', exact: true }).click();
  await page.getByRole('complementary', { name: 'Project controls' }).evaluate((panel) => { panel.scrollTop = 0; });
  await page.screenshot({ path: fileURLToPath(new URL('explorer-workflow-1440.png', screenshots)), animations: 'disabled' });
  assert.deepEqual(errors, []);
  console.log('Real LLT 2×2 study passed: optional axes, normalized grid and CSV, frozen inputs/conditions, exact-case geometry and both-axis report context.');
} finally { await browser.close(); }
