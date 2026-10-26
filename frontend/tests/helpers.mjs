// Shared browser-journey helpers for the project picker and Studies navigation.
export const projectTrigger = (page) => page.locator('button[aria-haspopup="dialog"][data-project-id]');
export const currentProjectId = (page) => projectTrigger(page).getAttribute('data-project-id');

export async function openProject(page, id) {
  await projectTrigger(page).click();
  await page.getByRole('combobox', { name: 'Search projects and simulations', exact: true }).fill(id);
  await page.locator(`[role="option"][data-project-id="${id}"]:not([data-simulation-id])`).click();
}

export async function waitForProject(page, id) {
  await page.waitForFunction((value) => document.querySelector('button[aria-haspopup="dialog"][data-project-id]')?.dataset.projectId === value, id);
}

export async function studyType(page, name) {
  await page.getByRole('navigation', { name: 'Study type', exact: true }).getByRole('button', { name: new RegExp(`^${name}`) }).click();
}
