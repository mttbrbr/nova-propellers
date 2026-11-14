import assert from 'node:assert/strict';
import { chromium } from 'playwright';

// Sections along the blade span in Design, and the OpenFAST structure blocks in Workflow.
const browser = await chromium.launch({ executablePath: process.env.NOVA_CHROMIUM_PATH === 'managed' ? undefined : process.env.NOVA_CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
try {
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto(process.env.NOVA_UI_TEST_URL || 'http://127.0.0.1:5174');

  // Design: a different section for each station along the span.
  await page.getByRole('button', { name: 'New project' }).click();
  await page.getByRole('textbox', { name: 'Project name' }).fill(`Span sections ${Date.now()}`);
  await page.getByRole('group', { name: 'Rotor type' }).getByRole('button', { name: 'HAWT', exact: true }).click();
  await page.getByRole('button', { name: /Continue to Geometry/ }).click();
  await page.getByRole('img', { name: /Chord in c\/R/ }).waitFor({ timeout: 30000 });
  await page.getByRole('button', { name: /Sections along the span/ }).click();
  assert.equal(await page.getByRole('combobox', { name: 'Station 1 section' }).count(), 0);
  const sent = page.waitForRequest((r) => r.url().includes('/rotors/analyze') && (r.postData() || '').includes('"sections"'));
  await page.getByRole('checkbox', { name: /Different section per station/ }).check();
  await sent;
  assert.equal(await page.getByRole('combobox', { name: 'Section', exact: true }).count(), 0, 'the single section selector is hidden while stations are used');
  await page.getByRole('combobox', { name: 'Station 2 section' }).selectOption('NACA 0012');
  await page.getByRole('button', { name: 'Add station' }).click();
  assert.equal(await page.getByRole('combobox', { name: /^Station \d section$/ }).count(), 3);
  await page.getByRole('img', { name: /Chord in c\/R/ }).waitFor();
  assert.equal(await page.getByRole('alert').count(), 0, 'no analysis error with several sections');
  await page.getByRole('button', { name: 'Remove station 3' }).click();
  await page.getByRole('checkbox', { name: /Different section per station/ }).uncheck();
  await page.getByRole('combobox', { name: 'Section', exact: true }).waitFor();

  // Workflow: the flexible template, the station tables and the tower shape.
  await page.getByRole('navigation', { name: 'Workspaces' }).getByRole('button', { name: 'Workflow', exact: true }).click();
  await page.getByRole('button', { name: 'Templates', exact: true }).click();
  await page.getByRole('button', { name: /flexible rotor/i }).first().click();
  const node = (text) => page.locator('.react-flow__node', { hasText: text }).first();
  await node('Blade structure').dispatchEvent('click');
  const table = page.getByRole('group', { name: 'stations table' });
  await table.waitFor();
  assert.equal(await table.getByRole('textbox', { name: /stations \d+ span_fraction/ }).count(), 11);
  await table.evaluate((el) => {
    const data = new DataTransfer();
    data.setData('text', '0\t10\t1e6\t2e6\n0.5\t5\t5e5\t1e6\n1\t2\t1e5\t3e5');
    el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true }));
  });
  await page.waitForFunction(() => document.querySelectorAll('[aria-label$="span_fraction"]').length === 3);

  await page.keyboard.press('Escape');
  await node('Tower').dispatchEvent('click');
  assert.equal(await page.getByRole('textbox', { name: 'base_diameter_m' }).count(), 0, 'table shape hides the tubular fields');
  await page.getByRole('combobox', { name: 'shape' }).selectOption('tubular');
  await page.getByRole('textbox', { name: 'base_diameter_m' }).waitFor();
  assert.equal(await page.getByRole('group', { name: 'stations table' }).count(), 0);
  // Without its diameters the tower reports what is missing and blocks the case.
  await page.getByRole('textbox', { name: 'base_diameter_m' }).fill('2');
  await page.getByRole('textbox', { name: 'top_diameter_m' }).fill('1');
  await page.getByRole('textbox', { name: 'wall_thickness_m' }).fill('0.02');

  // The case block builds the model without a solver and states its assumptions; the run block asks for OpenFAST.
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: 'Run workflow', exact: true }).click();
  await page.getByRole('region', { name: 'Run summary' }).waitFor({ timeout: 60000 });
  await node('OpenFAST case').dispatchEvent('click');
  const result = await page.getByRole('region', { name: 'Block result' }).innerText();
  assert.match(result, /Model notes/);
  assert.match(result, /Mode shapes/);
  assert.deepEqual(errors, []);
  console.log('Span sections and OpenFAST structure blocks passed');
} finally {
  await browser.close();
}
