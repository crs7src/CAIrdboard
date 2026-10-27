import { expect, test, type Page } from '@playwright/test'

const card = (over = {}) => ({
  key: 'AB-1',
  summary: 'First card',
  status: 'DEV In Progress',
  priority: 'High',
  url: 'https://x.atlassian.net/browse/AB-1',
  project: 'AB',
  description: 'Do the first thing',
  comments: [{ author: 'Ann', created: '2026-01-02T10:00:00.000+0000', body: 'Fix the button color', after_reopen: false }],
  status_history: [],
  reopened: false,
  last_reopened_at: null,
  eligible: true,
  repo_configured: true,
  ...over,
})

const plan = (over = {}) => ({
  card_key: 'AB-1',
  version: 1,
  state: 'ready',
  jira_status: 'DEV In Progress',
  feedback: null,
  plan: '## Steps\n\n1. Do the thing',
  error: null,
  created_at: 't',
  updated_at: 't',
  ...over,
})

/** Stateful in-browser fake of the plan endpoints; never touches Jira or the AI. */
async function mockBackend(page: Page, cardOver = {}) {
  let current: ReturnType<typeof plan> | null = null
  const posts: unknown[] = []
  await page.route('**/api/cards', (route) => route.fulfill({ json: [card(cardOver)] }))
  await page.route('**/api/plans', (route) =>
    route.fulfill({ json: current ? { 'AB-1': current.state } : {} }),
  )
  await page.route('**/api/ai-config', (route) =>
    route.fulfill({ json: { eligible_statuses: ['DEV In Progress'], project_repos: { AB: '/r' } } }),
  )
  await page.route('**/api/cards/AB-1', (route) => route.fulfill({ json: card(cardOver) }))
  await page.route('**/api/cards/AB-1/plan', (route) => {
    if (route.request().method() === 'POST') {
      posts.push(route.request().postDataJSON())
      current = plan({ version: (current?.version ?? 0) + 1, state: 'ready' })
      return route.fulfill({ status: 202, json: { ...current, state: 'running', plan: null } })
    }
    return current
      ? route.fulfill({ json: current })
      : route.fulfill({ status: 404, json: { detail: 'No plan exists for this card' } })
  })
  for (const decision of ['approve', 'reject'] as const) {
    await page.route(`**/api/cards/AB-1/plan/${decision}`, (route) => {
      current = plan({ ...current, state: decision === 'approve' ? 'approved' : 'rejected' })
      return route.fulfill({ json: current })
    })
  }
  return { posts }
}

test('generate, review and approve a plan for a card', async ({ page }) => {
  await mockBackend(page)
  await page.goto('/cards')
  await page.getByRole('link', { name: 'Plan', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'AB-1' })).toBeVisible()
  await expect(page.getByText('Do the first thing')).toBeVisible()
  await expect(page.getByText('Comments (1)')).toBeVisible()
  await expect(page.getByText('Fix the button color')).toBeVisible()

  await page.getByRole('button', { name: 'Generate plan' }).click()
  await expect(page.getByRole('heading', { name: 'Steps' })).toBeVisible({ timeout: 10_000 })
  await expect(page.getByText('Do the thing')).toBeVisible()

  await page.getByRole('button', { name: 'Approve' }).click()
  await expect(page.getByText('approved', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Approve' })).toHaveCount(0)
})

test('reject a plan and regenerate it with feedback', async ({ page }) => {
  const { posts } = await mockBackend(page)
  await page.goto('/cards/AB-1')
  await page.getByRole('button', { name: 'Generate plan' }).click()
  await expect(page.getByRole('heading', { name: 'Steps' })).toBeVisible({ timeout: 10_000 })
  await page.getByRole('button', { name: 'Reject' }).click()
  await expect(page.getByText('rejected', { exact: true })).toBeVisible()

  await page.getByLabel('What was wrong with this plan? (optional)').fill('Missing tests')
  await page.getByRole('button', { name: 'Regenerate plan' }).click()
  await expect(page.getByText('v2')).toBeVisible({ timeout: 10_000 })
  expect(posts).toEqual([{ feedback: null }, { feedback: 'Missing tests' }])
})

test('a card reopened earlier but now In Progress is flagged as rework', async ({ page }) => {
  await mockBackend(page, {
    status: 'In Progress',
    reopened: true,
    status_history: [{ from_status: 'Done', to_status: 'Reopened', when: '2026-01-02T09:00:00.000+0000', author: 'Ann' }],
  })
  await page.goto('/cards/AB-1')
  await expect(page.getByText('Reopened before')).toBeVisible()
  await expect(page.getByText('Done → Reopened')).toBeVisible()
})

test('cards in testing status cannot get a plan', async ({ page }) => {
  await mockBackend(page, { status: 'Testing', eligible: false })
  await page.goto('/cards/AB-1')
  await expect(page.getByText(/not generated for cards in "Testing"/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Generate plan' })).toHaveCount(0)
})
