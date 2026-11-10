import assert from 'node:assert/strict';
import { chromium } from 'playwright';

// Rotors workspace (Cp–λ, corrections, VAWT DMST, marine) and block workflows.
const browser = await chromium.launch({ executablePath: process.env.NOVA_CHROMIUM_PATH === 'managed' ? undefined : process.env.NOVA_CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
try {
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto(process.env.NOVA_UI_TEST_URL || 'http://127.0.0.1:5174');
  const rail = page.getByRole('navigation', { name: 'Workspaces' });

  // HAWT Cp–λ with a reference curve for the tip-loss comparison.
  await rail.getByRole('button', { name: 'Rotors', exact: true }).click();
  await page.getByRole('button', { name: 'Analyse rotor' }).click();
  await page.getByRole('img', { name: 'Power coefficient Cp versus λ' }).waitFor({ timeout: 60000 });
  assert.match(await page.getByRole('main', { name: 'Rotor performance' }).innerText(), /Cp max/);
  await page.getByRole('button', { name: 'Keep as reference' }).click();
  await page.getByRole('combobox', { name: 'Correction tip_loss' }).selectOption('none');
  await page.getByRole('button', { name: 'Analyse rotor' }).click();
  await page.getByText(/Reference \(dashed\): Tip loss: prandtl/).waitFor();
  await page.screenshot({ path: process.env.NOVA_SCREENSHOT_DIR ? `${process.env.NOVA_SCREENSHOT_DIR}/rotors-hawt.png` : '/dev/null' });

  // VAWT with the double-multiple streamtube model and dynamic stall.
  await page.getByRole('group', { name: 'Rotor family' }).getByRole('button', { name: 'VAWT' }).click();
  await page.getByRole('combobox', { name: 'VAWT method' }).selectOption('double_multiple_streamtube');
  await page.getByRole('combobox', { name: 'Correction dynamic_stall' }).selectOption('gormont_berg');
  await page.getByRole('button', { name: 'Analyse rotor' }).click();
  await page.getByRole('img', { name: /Blade torque/ }).waitFor({ timeout: 90000 });
  assert.match(await page.getByRole('region', { name: 'Rotor results' }).innerText(), /Double-multiple streamtube/);
  await page.screenshot({ path: process.env.NOVA_SCREENSHOT_DIR ? `${process.env.NOVA_SCREENSHOT_DIR}/rotors-vawt.png` : '/dev/null' });

  // Marine propeller: open-water diagram and cavitation assessment.
  await page.getByRole('group', { name: 'Rotor family' }).getByRole('button', { name: 'Marine' }).click();
  await page.getByRole('button', { name: 'Analyse rotor' }).click();
  await page.getByRole('region', { name: 'Marine assessment' }).waitFor({ timeout: 60000 });
  assert.match(await page.getByRole('region', { name: 'Marine assessment' }).innerText(), /Keller min/);
  assert.ok(await page.getByRole('img', { name: 'Open-water diagram versus J' }).isVisible());

  // Block workflows: load the marine template, run, tighten a limit and stop downstream.
  await rail.getByRole('button', { name: 'Workflow', exact: true }).click();
  await page.getByRole('group', { name: 'Workflow type' }).getByRole('button', { name: 'Block workflows' }).click();
  await page.getByRole('combobox', { name: 'Load template' }).selectOption('marine_cavitation');
  await page.getByRole('button', { name: 'Run workflow', exact: true }).click();
  await page.getByText('all hard constraints satisfied').waitFor({ timeout: 60000 });
  assert.match(await page.getByRole('region', { name: 'Block inspector' }).innerText(), /Constraints · cavitation/);
  await page.screenshot({ path: process.env.NOVA_SCREENSHOT_DIR ? `${process.env.NOVA_SCREENSHOT_DIR}/blocks-marine.png` : '/dev/null' });

  await page.locator('.react-flow__node', { hasText: 'cavitation' }).click();
  await page.getByRole('button', { name: 'JSON view' }).click();
  await page.getByRole('textbox', { name: 'Block configuration JSON' }).fill(JSON.stringify({
    checks: [{ preset: 'burrill', value: 0.1 }], on_violation: 'stop' }));
  await page.getByRole('button', { name: 'Run workflow', exact: true }).click();
  await page.getByText('constraint violation').waitFor({ timeout: 60000 });
  assert.match(await page.getByRole('region', { name: 'Block result' }).innerText(), /violated/);

  // Save the workflow, then add a general block from the palette.
  await page.getByRole('textbox', { name: 'Workflow name' }).fill('Browser block workflow');
  await page.getByRole('button', { name: 'Save workflow', exact: true }).click();
  await page.getByText('Saved revision 1').waitFor();
  await page.getByRole('button', { name: '+ Expression' }).click();
  assert.ok(await page.locator('.react-flow__node', { hasText: 'expression_1' }).isVisible());
  await page.getByRole('button', { name: 'Validate' }).click();
  await page.getByRole('alert').filter({ hasText: 'Unconnected required input: expression_1.values' }).waitFor();
  assert.deepEqual(errors, []);
  console.log('Rotors and block workflow journey passed');
} finally {
  await browser.close();
}
