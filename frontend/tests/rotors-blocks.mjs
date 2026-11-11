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
  const shot = async (name) => { if (process.env.NOVA_SCREENSHOT_DIR) await page.screenshot({ path: `${process.env.NOVA_SCREENSHOT_DIR}/${name}.png` }); };

  const sheet = page.getByRole('navigation', { name: 'Design stages' });
  // Open a design-sheet section as the active view (a second click on the active one folds it).
  const stages = { getByRole: (_role, { name }) => ({ click: async () => {
    const title = sheet.getByRole('button', { name, exact: true });
    await title.click();
    if (await title.getAttribute('aria-expanded') !== 'true') await title.click();
  } }) };
  const family = (name) => page.getByRole('group', { name: 'Rotor type' }).getByRole('button', { name, exact: true }).click();
  const correctionBoxes = async () => page.getByRole('combobox', { name: /^Correction / }).evaluateAll((items) => items.map((i) => i.getAttribute('aria-label')));

  // One Design flow: the rotor type is chosen in Sizing and every stage adapts.
  await page.getByRole('textbox', { name: 'Project name' }).fill(`Rotor families ${Date.now()}`);
  await family('HAWT');
  await page.getByRole('spinbutton', { name: 'Rated power' }).fill('20000');
  await page.getByRole('button', { name: 'Apply to geometry' }).click();
  await page.getByRole('button', { name: /Continue to Geometry/ }).click();
  await page.getByRole('img', { name: /Chord in c\/R/ }).waitFor({ timeout: 30000 });
  await page.getByRole('button', { name: /Continue to Analysis/ }).click();
  assert.deepEqual(await correctionBoxes(), ['Correction tip_loss', 'Correction hub_loss', 'Correction high_induction', 'Correction rotational_augmentation']);
  assert.match(await page.getByRole('region', { name: 'Not applicable' }).innerText(), /Compressibility/);
  await page.getByRole('button', { name: 'Run analysis' }).click();
  await page.getByRole('dialog', { name: /^Run / }).getByRole('button', { name: 'Start run', exact: true }).click();
  await page.getByRole('img', { name: 'Power coefficient Cp versus λ' }).waitFor({ timeout: 60000 });
  assert.match(await page.getByRole('region', { name: 'Performance' }).innerText(), /Cp max/);
  await shot('rotors-hawt');

  // Change a correction, run again and compare the two runs of the same simulation.
  await stages.getByRole('button', { name: 'Analysis', exact: true }).click();
  await page.getByRole('combobox', { name: 'Correction tip_loss' }).selectOption('none');
  await page.getByRole('button', { name: 'Run analysis' }).click();
  await page.getByRole('dialog', { name: /^Run / }).getByRole('button', { name: 'Start run', exact: true }).click();
  await page.getByRole('img', { name: 'Power coefficient Cp versus λ' }).waitFor({ timeout: 60000 });
  const compare = page.getByRole('combobox', { name: 'Compare with run' });
  await page.waitForFunction(() => document.querySelector('select[aria-label="Compare with run"]')?.options.length > 1);
  await compare.selectOption({ index: 1 });
  await page.getByText('Compared run').first().waitFor();

  // VAWT: double-multiple streamtube with dynamic stall; a new simulation draft.
  await stages.getByRole('button', { name: 'Sizing', exact: true }).click();
  await family('VAWT');
  await stages.getByRole('button', { name: 'Analysis', exact: true }).click();
  assert.ok((await correctionBoxes()).includes('Correction dynamic_stall'));
  await page.getByRole('combobox', { name: 'VAWT method' }).selectOption('double_multiple_streamtube');
  await page.getByRole('combobox', { name: 'Correction dynamic_stall' }).selectOption('gormont_berg');
  await page.getByRole('button', { name: 'Run analysis' }).click();
  await page.getByRole('dialog', { name: /^Run / }).getByRole('button', { name: 'Start run', exact: true }).click();
  await page.getByRole('img', { name: /Blade torque/ }).waitFor({ timeout: 90000 });
  assert.match(await page.getByRole('region', { name: 'Performance' }).innerText(), /Cp – λ/);
  await shot('rotors-vawt');

  // Marine propeller: only tip and hub loss apply; open-water diagram and cavitation.
  await stages.getByRole('button', { name: 'Sizing', exact: true }).click();
  await family('Marine');
  await page.getByRole('button', { name: 'Apply to geometry' }).click();
  await stages.getByRole('button', { name: 'Analysis', exact: true }).click();
  assert.deepEqual(await correctionBoxes(), ['Correction tip_loss', 'Correction hub_loss']);
  await page.getByRole('button', { name: 'Run analysis' }).click();
  await page.getByRole('dialog', { name: /^Run / }).getByRole('button', { name: 'Start run', exact: true }).click();
  await page.getByRole('region', { name: 'Marine assessment' }).waitFor({ timeout: 60000 });
  assert.ok(await page.getByRole('img', { name: 'Open-water diagram versus J' }).isVisible());
  assert.match(await page.getByRole('region', { name: 'Requirement check' }).innerText(), /Propeller thrust required/);
  await shot('rotors-marine');

  // Projects open as tabs: a new draft gets its own tab, the saved project reopens from its tab.
  const projectTabs = page.getByRole('tablist', { name: 'Open projects' });
  await projectTabs.getByRole('tab', { name: /^Rotor families/ }).waitFor();
  await page.getByRole('button', { name: 'Create a new project' }).click();
  await projectTabs.getByRole('tab', { name: /Unsaved draft/ }).waitFor();
  await projectTabs.getByRole('tab', { name: /^Rotor families/ }).click();
  await page.waitForFunction(() => document.querySelector('[aria-label="Open projects"] [aria-selected="true"]')?.textContent.includes('Rotor families'));
  await page.getByRole('region', { name: 'Marine assessment' }).or(page.getByRole('navigation', { name: 'Design stages' })).first().waitFor();

  // Back to the air propeller: the native actuator-disk sizing returns.
  await stages.getByRole('button', { name: 'Sizing', exact: true }).click();
  await family('Air');
  await page.getByRole('img', { name: /Ideal actuator disk/ }).waitFor();

  // Block workflows: load the marine template, run, tighten a limit and stop downstream.
  await rail.getByRole('button', { name: 'Workflow', exact: true }).click();
  await page.getByRole('group', { name: 'Workflow type' }).getByRole('button', { name: 'Block workflows' }).click();
  await page.getByRole('combobox', { name: 'Load template' }).selectOption('marine_cavitation');
  await page.getByRole('button', { name: 'Run workflow', exact: true }).click();
  await page.getByText('all hard constraints satisfied').waitFor({ timeout: 60000 });
  assert.match(await page.getByRole('region', { name: 'Block inspector' }).innerText(), /Constraints · cavitation/);
  await shot('blocks-marine');

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
