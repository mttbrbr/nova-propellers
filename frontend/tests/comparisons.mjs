import assert from 'node:assert/strict';
import { chromium } from 'playwright';

// Comparisons workspace: runs from different projects overlaid, inputs diffed against a baseline.
const browser = await chromium.launch({ executablePath: process.env.NOVA_CHROMIUM_PATH === 'managed' ? undefined : process.env.NOVA_CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
try {
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const api = process.env.NOVA_API_TEST_URL || 'http://127.0.0.1:8777/api';
  const post = async (path, data) => {
    const response = await page.request.post(`${api}${path}`, { data });
    assert.ok(response.ok(), `${path}: ${response.status()} ${await response.text()}`);
    return response.json();
  };
  const stamp = Date.now();
  const make = async (name, spec) => {
    const project = await post('/v2/projects', { name: `${name} ${stamp}` });
    const simulation = await post('/v2/simulations', { project_id: project.id, name: 'Rotor', kind: 'rotor', configuration: { spec: { kind: 'hawt', curve: { start: 2, stop: 12, points: 11 }, ...spec } } });
    const run = await post(`/v2/simulations/${simulation.id}/run`, {});
    assert.equal(run.state, 'succeeded', run.error);
    return project;
  };
  const base = await make('Baseline rotor', {});
  const wide = await make('Wider rotor', { geometry: { radius_m: 6, blades: 4 } });
  const lossless = await make('No tip loss', { corrections: { tip_loss: 'none' } });

  await page.goto(process.env.NOVA_UI_TEST_URL || 'http://127.0.0.1:5174');
  await page.getByRole('navigation', { name: 'Workspaces' }).getByRole('button', { name: 'Comparisons', exact: true }).click();
  const addRun = async (project) => {
    await page.getByRole('combobox', { name: 'Project to add runs from' }).selectOption(project.id);
    await page.getByRole('button', { name: /^Rotor · BEMT/ }).first().click();
  };
  await addRun(base);
  await addRun(wide);
  await page.getByRole('img', { name: 'Cp – λ for 2 runs' }).waitFor({ timeout: 20000 });
  const differences = page.getByRole('table', { name: 'Input differences' });
  assert.match(await differences.innerText(), /geometry\.radius_m/);
  assert.match(await differences.innerText(), /geometry\.blades/);
  await page.getByText(/differs in 2 inputs: its Δ cannot be attributed to a single cause/).waitFor();
  await addRun(lossless);
  await page.getByRole('img', { name: 'Cp – λ for 3 runs' }).waitFor();
  assert.match(await differences.innerText(), /corrections\.tip_loss/);
  assert.equal(await page.getByRole('table', { name: 'Compared results' }).getByRole('row').count(), 4);
  await page.getByRole('group', { name: 'Quantity' }).getByRole('button', { name: 'Thrust along the blade' }).click();
  await page.getByRole('img', { name: 'Thrust along the blade for 3 runs' }).waitFor();

  await page.getByRole('textbox', { name: 'Comparison name' }).fill(`Tip loss and size ${stamp}`);
  await page.getByRole('button', { name: 'Save comparison', exact: true }).click();
  await page.getByRole('button', { name: `Tip loss and size ${stamp} · 3 runs` }).waitFor();
  assert.deepEqual(errors, []);
  console.log('Comparisons across projects: overlay, baseline deltas, input diff with attribution warning and saved comparison passed');
} finally {
  await browser.close();
}
