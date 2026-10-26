import assert from 'node:assert/strict';
import { chromium } from 'playwright';

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
  const inputs = { project_name: 'Native monitoring retry browser project', propeller_type: 'traditional', thrust_target: 10, rpm: 5000, diameter: .25, blades: 2, airfoil: 'NACA 4412', geometry_method: 'bezier', airfoil_assignments: [], geometry_parameters: {
    chord_points: [{ x: 0, y: .02625 }, { x: .32, y: .02875 }, { x: .72, y: .01625 }, { x: 1, y: .0045 }],
    twist_points: [{ x: 0, y: 34 }, { x: .33, y: 25 }, { x: .72, y: 14 }, { x: 1, y: 7 }],
  } };
  const template = await (await page.request.get(`${api}/v1/workflow-template`)).json();
  const workflow = { ...template, nodes: template.nodes.map((n) => n.type === 'analysis' ? { ...n, config: { ...n.config, model: 'llt' } } : n) };
  const definition = { name: inputs.project_name, inputs, workflow, conditions: { air_density_kg_m3: 1.225, air_viscosity_pa_s: 1.81e-5 } };
  const project = await post('/v1/projects', definition);
  const simulation = await post('/v1/simulations', { ...definition, name: 'LLT monitoring recovery', project_id: project.id, geometry_id: project.geometry_id, geometry_revision: project.geometry_revision });
  await page.goto(process.env.NOVA_UI_TEST_URL || 'http://127.0.0.1:5174');
  await page.getByRole('combobox', { name: 'Open saved project', exact: true }).selectOption(project.id);
  const context = page.locator('[aria-label="Project and simulation context"]');
  await context.getByText('Simulation · saved', { exact: true }).waitFor();
  let submissions = 0;
  let failedPolls = 0;
  let resumedPolls = 0;
  let submitted;
  page.on('request', (request) => { if (request.method() === 'POST' && request.url().endsWith(`/simulations/${simulation.id}/run`)) submissions += 1; });
  await page.route(/\/api\/v1\/runs\/[^/]+$/, async (route) => {
    if (route.request().method() !== 'GET') return route.continue();
    if (failedPolls === 0) {
      failedPolls += 1;
      const response = await route.fetch();
      return route.fulfill({ response, status: 503, json: { detail: 'Temporary monitor transport failure (test)' } });
    }
    resumedPolls += 1;
    return route.continue();
  });
  const response = page.waitForResponse((item) => item.request().method() === 'POST' && item.url().endsWith(`/simulations/${simulation.id}/run`));
  await page.getByRole('button', { name: 'Run simulation', exact: true }).click();
  submitted = await (await response).json();
  assert.ok(['queued', 'running'].includes(submitted.state));
  await context.getByRole('alert').filter({ hasText: 'Connection interrupted while monitoring the run. Retrying; the submitted job is unchanged.' }).waitFor();
  await page.getByRole('button', { name: 'Export CSV', exact: true }).waitFor({ timeout: 30000 });
  const run = page.getByRole('button', { name: 'Run simulation', exact: true });
  await page.waitForFunction(() => { const button = [...document.querySelectorAll('button')].find((item) => item.textContent.trim() === 'Run simulation'); return Boolean(button && !button.disabled); });
  assert.equal(await run.isEnabled(), true);
  assert.equal(await page.getByText('Connection interrupted while monitoring the run. Retrying; the submitted job is unchanged.', { exact: true }).count(), 0);
  assert.equal(submissions, 1, 'Monitoring retry must not submit another numerical execution');
  assert.equal(failedPolls, 1);
  assert.ok(resumedPolls >= 1);
  const persisted = await (await page.request.get(`${api}/v1/runs/${submitted.id}`)).json();
  assert.equal(persisted.state, 'succeeded');
  assert.equal(persisted.simulation_id, simulation.id);
  assert.equal(persisted.result.analyses[0].model, 'llt');
  const projectRuns = (await (await page.request.get(`${api}/v1/runs`)).json()).filter((record) => record.project_id === project.id);
  assert.equal(projectRuns.length, 1);
  await page.getByRole('navigation', { name: 'Workspace navigation' }).getByRole('button', { name: 'Results', exact: true }).click();
  await page.getByText('Technical report', { exact: true }).waitFor();
  await context.getByText(new RegExp(`Viewing LLT monitoring recovery.*LLT.*run ${submitted.id.slice(0, 8)}`)).waitFor();
  assert.deepEqual(errors, []);
  console.log('Native execution monitoring recovered after one HTTP 503: visible retry notice, one submission, successful same-run LLT result and unlocked controls.');
} finally { await browser.close(); }
