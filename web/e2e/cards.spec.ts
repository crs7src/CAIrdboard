import { expect, test } from '@playwright/test'

const cards = [
  { key: 'AB-1', summary: 'First card', status: 'To Do', priority: 'High', url: 'https://x.atlassian.net/browse/AB-1' },
  { key: 'AB-2', summary: 'Second card', status: 'In Progress', priority: null, url: 'https://x.atlassian.net/browse/AB-2' },
]

test('cards page lists assigned Jira cards and re-syncs', async ({ page }) => {
  let calls = 0
  await page.route('**/api/cards', (route) => {
    calls++
    return route.fulfill({ json: cards })
  })
  await page.goto('/')
  await page.getByRole('link', { name: 'My Cards' }).click()
  await expect(page.getByRole('link', { name: 'AB-1' })).toBeVisible()
  await expect(page.getByText(/Second card/)).toBeVisible()

  const before = calls
  await page.getByRole('button', { name: 'Sync' }).click()
  await expect.poll(() => calls).toBeGreaterThan(before)
})

test('cards page shows an error when Jira is not configured', async ({ page }) => {
  await page.route('**/api/cards', (route) =>
    route.fulfill({ status: 503, json: { detail: 'Jira is not configured' } }),
  )
  await page.goto('/cards')
  await expect(page.getByRole('alert')).toHaveText('Jira is not configured')
})
