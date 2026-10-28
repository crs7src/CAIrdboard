import { expect, test } from '@playwright/test'

const cards = [
  { key: 'AB-1', summary: 'First card', status: 'To Do', priority: 'High', url: 'https://x.atlassian.net/browse/AB-1', project: 'AB', description: '' },
  { key: 'AB-2', summary: 'Second card', status: 'In Progress', priority: null, url: 'https://x.atlassian.net/browse/AB-2', project: 'AB', description: '' },
]

test('home page splits cards into sections and re-syncs', async ({ page }) => {
  let calls = 0
  await page.route('**/api/plans', (route) => route.fulfill({ json: { 'AB-2': 'ready' } }))
  await page.route('**/api/reviews', (route) => route.fulfill({ json: {} }))
  await page.route('**/api/implementations', (route) => route.fulfill({ json: {} }))
  await page.route('**/api/ai-config', (route) =>
    route.fulfill({ json: { eligible_statuses: ['To Do'], project_repos: {} } }),
  )
  await page.route('**/api/cards', (route) => {
    calls++
    return route.fulfill({ json: cards })
  })
  await page.goto('/')
  await expect(page.getByRole('region', { name: 'To Do' }).getByRole('link', { name: /AB-1/ })).toBeVisible()
  await expect(page.getByRole('region', { name: 'In Review/Done' }).getByText('Second card')).toBeVisible()
  // Only the To Do card is eligible for a plan.
  await expect(page.getByText('Plan: available')).toHaveCount(1)

  const before = calls
  await page.getByRole('button', { name: 'Sync' }).click()
  await expect.poll(() => calls).toBeGreaterThan(before)
})

test('home page shows an error when Jira is not configured', async ({ page }) => {
  await page.route('**/api/cards', (route) =>
    route.fulfill({ status: 503, json: { detail: 'Jira is not configured' } }),
  )
  await page.goto('/')
  await expect(page.getByRole('alert')).toContainText('Jira is not configured')
})
