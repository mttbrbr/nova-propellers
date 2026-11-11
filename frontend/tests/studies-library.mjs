import assert from 'node:assert/strict';
import { chromium } from 'playwright';
import { currentProjectId, openProject, studyType, waitForProject } from './helpers.mjs';

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
  const finished = async (run) => {
    for (let attempt = 0; attempt < 240; attempt += 1) {
      const current = await (await page.request.get(`${api}/v1/runs/${run.id}`)).json();
      if (!['queued', 'running', 'cancelling'].includes(current.state)) return current;
      await page.waitForTimeout(250);
    }
    throw new Error('Run did not finish');
  };
  const stamp = Date.now();
  const template = await (await page.request.get(`${api}/v1/workflow-template`)).json();
  const polar = await post('/v1/assets/demonstration-polar', { airfoil: 'NACA 4412' });
  const create = async (name, scale, model) => {
    const inputs = { project_name: name, propeller_type: 'traditional', thrust_target: 10, rpm: 5000, diameter: .25, blades: 2, airfoil: 'NACA 4412', geometry_method: 'bezier', airfoil_assignments: [], geometry_parameters: {
      chord_points: [{ x: 0, y: .02625 * scale }, { x: .32, y: .02875 * scale }, { x: .72, y: .01625 * scale }, { x: 1, y: .0045 * scale }],
      twist_points: [{ x: 0, y: 34 }, { x: .33, y: 25 }, { x: .72, y: 14 }, { x: 1, y: 7 }] } };
    const workflow = { ...template, nodes: template.nodes.map((n) => n.type === 'analysis' ? { ...n, config: { ...n.config, model } } : n) };
    const definition = { name, inputs, workflow, conditions: { air_density_kg_m3: 1.225, air_viscosity_pa_s: 1.81e-5 }, polar_asset_id: polar.id };
    const project = await post('/v1/projects', definition);
    const simulation = await post('/v1/simulations', { ...definition, name: `${name} baseline`, project_id: project.id, geometry_id: project.geometry_id, geometry_revision: project.geometry_revision });
    const run = await finished(await post(`/v1/simulations/${simulation.id}/run`, { expected_revision: simulation.revision }));
    assert.equal(run.state, 'succeeded', run.error);
    return { project, simulation };
  };
  const reference = await create(`Library reference ${stamp}`, 1, 'bemt');
  const wide = await create(`Library wide chord ${stamp}`, 1.25, 'llt');
  await page.goto(process.env.NOVA_UI_TEST_URL || 'http://127.0.0.1:5174');

  // Ctrl+P searches every project and opens the chosen one.
  await page.getByRole('button', { name: 'More actions', exact: true }).waitFor();
  await page.keyboard.press('Control+p');
  await page.getByRole('combobox', { name: 'Search projects and simulations', exact: true }).fill(`wide chord ${stamp}`);
  await page.locator(`[role="option"][data-project-id="${wide.project.id}"]`).first().waitFor();
  await page.keyboard.press('Enter');
  await waitForProject(page, wide.project.id);

  // Library lists, searches and compares saved projects.
  await page.getByRole('navigation', { name: 'Workspaces' }).getByRole('button', { name: 'Library', exact: true }).click();
  const table = page.getByRole('table', { name: 'Saved projects', exact: true });
  await table.locator(`tr[data-project-id="${reference.project.id}"]`).waitFor();
  await page.getByRole('textbox', { name: 'Search projects', exact: true }).fill(`${stamp}`);
  assert.equal(await table.locator('tbody tr').count(), 2);
  await page.getByRole('checkbox', { name: `Select ${reference.project.name}`, exact: true }).check();
  await page.getByRole('checkbox', { name: `Select ${wide.project.name}`, exact: true }).check();
  await page.getByRole('button', { name: 'Compare results', exact: true }).click();
  const designTable = page.getByRole('table', { name: 'Design comparison results', exact: true });
  await designTable.waitFor();
  assert.equal(await designTable.getByRole('row').count(), 3);
  await page.getByText(/differs from A in solver/).waitFor();

  // "Also compare with" runs the same frozen simulation with a second solver after the main run.
  await openProject(page, reference.project.id);
  await waitForProject(page, reference.project.id);
  await page.getByRole('navigation', { name: 'Workspaces' }).getByRole('button', { name: 'Design', exact: true }).click();
  await page.getByRole('navigation', { name: 'Design stages' }).getByRole('button', { name: 'Analysis', exact: true }).click();
  await page.getByRole('checkbox', { name: /^Also compare with .*Lifting/ }).check();
  const comparison = page.waitForResponse((response) => response.url().endsWith(`/simulations/${reference.simulation.id}/solver-comparison`) && response.request().method() === 'POST', { timeout: 60000 });
  await page.getByRole('button', { name: 'Run simulation', exact: true }).click();
  const queued = await (await comparison).json();
  assert.equal(queued.comparison.kind, 'solver');
  assert.equal((await finished(queued)).state, 'succeeded');
  const simulations = await (await page.request.get(`${api}/v1/projects/${reference.project.id}/simulations`)).json();
  assert.equal(simulations.length, 1, 'A solver comparison must not create simulations');
  await page.getByRole('navigation', { name: 'Workspaces' }).getByRole('button', { name: 'Studies', exact: true }).click();
  await studyType(page, 'Solver comparison');
  await page.getByRole('button', { name: `Open study ${queued.id.slice(0, 8)}`, exact: true }).click();
  const solverTable = page.getByRole('table', { name: 'Solver comparison results', exact: true });
  await solverTable.getByText('Reference', { exact: true }).waitFor({ timeout: 30000 });
  assert.equal(await solverTable.getByRole('row').count(), 3);
  await page.getByRole('navigation', { name: 'Workspaces' }).getByRole('button', { name: 'Design', exact: true }).click();
  await page.getByRole('navigation', { name: 'Design stages' }).getByRole('button', { name: 'Results', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('select[aria-label="Compare with run"]')?.value.startsWith('cmp:'));

  // Deleting asks for the project name and removes it with its runs.
  await page.getByRole('navigation', { name: 'Workspaces' }).getByRole('button', { name: 'Library', exact: true }).click();
  await page.getByRole('textbox', { name: 'Search projects', exact: true }).fill(wide.project.name);
  await table.locator(`tr[data-project-id="${wide.project.id}"]`).click();
  await page.getByRole('button', { name: 'Delete project…', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: `Delete “${wide.project.name}”?` });
  assert.equal(await dialog.getByRole('button', { name: 'Delete permanently', exact: true }).isEnabled(), false);
  await dialog.getByRole('textbox', { name: 'Confirmation', exact: true }).fill(wide.project.name);
  await dialog.getByRole('button', { name: 'Delete permanently', exact: true }).click();
  await table.locator(`tr[data-project-id="${wide.project.id}"]`).waitFor({ state: 'detached' });
  assert.equal((await page.request.get(`${api}/v2/projects/${wide.project.id}`)).status(), 404);
  assert.equal(await currentProjectId(page), reference.project.id);
  assert.deepEqual(errors, []);
  console.log('Project picker, Library projects, design and solver comparisons, compare-on-run and confirmed deletion passed.');
} finally { await browser.close(); }
