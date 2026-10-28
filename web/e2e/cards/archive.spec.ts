import { expect, test, type Page } from '@playwright/test'

const card = (key: string, status: string) => ({
  key, summary: `Summary ${key}`, status, priority: null,
  url: `https://x.atlassian.net/browse/${key}`, project: 'AB', description: '', comments: [],
})

async function mockApi(page: Page) {
  const archived: string[] = []
  await page.route('**/api/cards', (route) =>
    route.fulfill({ json: [card('AB-1', 'To Do'), card('AB-2', 'Done')] }),
  )
  await page.route('**/api/ai-config', (route) =>
    route.fulfill({ json: { eligible_statuses: ['To Do'], project_repos: { AB: '/r' } } }),
  )
  for (const path of ['plans', 'reviews', 'tests', 'implementations', 'merge-requests', 'merge-requests/urls']) {
    await page.route(`**/api/${path}`, (route) => route.fulfill({ json: {} }))
  }
  await page.route('**/api/test-approvals', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/archive', (route) => route.fulfill({ json: [...archived] }))
  await page.route('**/api/cards/*/archive', (route) => {
    const key = route.request().url().split('/').at(-2) as string
    if (route.request().method() === 'PUT') archived.push(key)
    else archived.splice(archived.indexOf(key), 1)
    return route.fulfill({ status: 204 })
  })
}

test('archive a Done card, find it in the archive, unarchive it', async ({ page }) => {
  await mockApi(page)
  await page.goto('/')
  await expect(page.getByRole('link', { name: /AB-2/ })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Archive AB-1' })).toHaveCount(0)

  await page.getByRole('button', { name: 'Archive AB-2' }).click()
  await expect(page.getByRole('link', { name: /AB-2/ })).toHaveCount(0)
  await expect(page.getByRole('link', { name: /AB-1/ })).toBeVisible()

  await page.getByRole('button', { name: 'View archive' }).click()
  await expect(page).toHaveURL(/\/archive$/)
  await expect(page.getByRole('link', { name: 'AB-2', exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'AB-1', exact: true })).toHaveCount(0)

  await page.getByRole('button', { name: 'Unarchive AB-2' }).click()
  await expect(page.getByText('No archived cards.')).toBeVisible()

  await page.getByRole('link', { name: 'Back to cards' }).click()
  await expect(page.getByRole('link', { name: /AB-2/ })).toBeVisible()
})
