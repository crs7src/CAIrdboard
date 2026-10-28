import { expect, test } from '@playwright/test'

test('home page shows the title and no summary', async ({ page }) => {
  await page.route('**/api/cards', (route) => route.fulfill({ json: [] }))
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: 'CAIrdboard' })).toBeVisible()
  await expect(page.getByText(/Review the Jira cards assigned to you/)).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'My Cards' })).toHaveCount(0)
})

const polledCard = {
  key: 'AB-1', summary: 'Add dark mode', status: 'To Do', priority: null,
  url: 'https://x.atlassian.net/browse/AB-1', project: 'AB', description: '', comments: [],
}

async function mockPolling(page: import('@playwright/test').Page, finalState: string) {
  let polls = 0
  await page.route('**/api/cards', (route) => route.fulfill({ json: [polledCard] }))
  await page.route('**/api/ai-config', (route) =>
    route.fulfill({ json: { eligible_statuses: ['To Do'], project_repos: { AB: '/r' } } }),
  )
  await page.route('**/api/plans', (route) => route.fulfill({ json: { 'AB-1': 'approved' } }))
  await page.route('**/api/reviews', (route) => route.fulfill({ json: {} }))
  await page.route('**/api/tests', (route) => route.fulfill({ json: {} }))
  await page.route('**/api/test-approvals', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/test-configs', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/merge-requests', (route) => route.fulfill({ json: {} }))
  await page.route('**/api/merge-requests/urls', (route) => route.fulfill({ json: {} }))
  await page.route('**/api/implementations', (route) =>
    route.fulfill({ json: { 'AB-1': polls++ < 1 ? 'running' : finalState } }),
  )
}

test('a running step turns into a green check once the poll reports completed', async ({ page }) => {
  await mockPolling(page, 'completed')
  await page.goto('/')
  await expect(page.getByRole('progressbar')).toBeVisible()
  await expect(page.getByRole('img', { name: 'Implement' })).toBeVisible({ timeout: 10_000 })
  await expect(page.getByRole('progressbar')).toHaveCount(0)
})

test('a running step turns into a failed icon once the poll reports failed', async ({ page }) => {
  await mockPolling(page, 'failed')
  await page.goto('/')
  await expect(page.getByRole('progressbar')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Implement failed' })).toBeVisible({ timeout: 10_000 })
  await expect(page.getByRole('progressbar')).toHaveCount(0)
})
