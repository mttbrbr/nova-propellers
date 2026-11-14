import assert from 'node:assert/strict';
import { chromium } from 'playwright';

// Settings: integrations section, shortcuts, entry points, and the OpenFAST block's executable selector.
const browser = await chromium.launch({ executablePath: process.env.NOVA_CHROMIUM_PATH === 'managed' ? undefined : process.env.NOVA_CHROMIUM_PATH || '/usr/bin/chromium', headless: true, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
try {
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto(process.env.NOVA_UI_TEST_URL || 'http://127.0.0.1:5174');
  const rail = page.getByRole('navigation', { name: 'Workspaces' });
  assert.equal(await rail.getByRole('button', { name: 'Integrations', exact: true }).count(), 0);

  await rail.getByRole('button', { name: 'Settings', exact: true }).click();
  await page.getByRole('region', { name: 'OpenFAST' }).waitFor();
  await page.getByRole('region', { name: 'PyWake' }).waitFor();
  const path = page.getByRole('textbox', { name: 'OpenFAST executable' });
  await path.fill('/nonexistent/openfast');
  await page.getByRole('region', { name: 'OpenFAST' }).getByRole('button', { name: 'Detect only' }).click();
  await page.getByText(/Unavailable/).first().waitFor();
  if (process.env.NOVA_SCREENSHOT_DIR) await page.screenshot({ path: `${process.env.NOVA_SCREENSHOT_DIR}/settings.png` });

  await page.getByRole('navigation', { name: 'Settings sections' }).getByRole('button', { name: 'Shortcuts' }).click();
  await page.getByRole('region', { name: 'Workflow' }).getByText('Search blocks').waitFor();

  // Entry points: header menu and Ctrl+,
  await rail.getByRole('button', { name: 'Workflow', exact: true }).click();
  await page.keyboard.press('Control+,');
  await page.getByRole('navigation', { name: 'Settings sections' }).waitFor();
  await rail.getByRole('button', { name: 'Workflow', exact: true }).click();
  await page.getByRole('button', { name: 'More actions' }).click();
  await page.getByRole('dialog', { name: 'More actions' }).getByRole('button', { name: /^Full screen/ }).waitFor();
  await page.getByRole('dialog', { name: 'More actions' }).getByRole('button', { name: /^Settings/ }).click();
  await page.getByRole('navigation', { name: 'Settings sections' }).waitFor();

  // The legacy cases and results view stays reachable from Settings.
  await page.getByRole('navigation', { name: 'Settings sections' }).getByRole('button', { name: 'Integrations' }).click();
  await page.getByRole('button', { name: 'Open external cases and results' }).click();
  await page.getByRole('heading', { name: 'Integrations' }).first().waitFor();

  // OpenFAST block: no executable configured shows a setup shortcut that opens Settings.
  await rail.getByRole('button', { name: 'Workflow', exact: true }).click();
  await page.getByRole('button', { name: 'Templates', exact: true }).click();
  await page.getByRole('button', { name: /OpenFAST run with limits/ }).click();
  await page.locator('.react-flow__node', { hasText: 'run' }).first().click();
  const setup = page.getByRole('button', { name: 'Set up OpenFAST' });
  const selector = page.getByRole('combobox', { name: 'OpenFAST executable' });
  await setup.or(selector).first().waitFor();
  if (await setup.count()) { await setup.click(); await page.getByRole('navigation', { name: 'Settings sections' }).waitFor(); }
  assert.deepEqual(errors, []);
  console.log('Settings journey passed');
} finally {
  await browser.close();
}
