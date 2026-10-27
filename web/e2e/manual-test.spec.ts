import { expect, test } from '@playwright/test'

const card = {
  key: 'AB-1',
  summary: 'Add dark mode',
  status: 'DEV In Progress',
  priority: null,
  url: 'https://x.atlassian.net/browse/AB-1',
  project: 'AB',
  description: '',
  comments: [],
  eligible: true,
  repo_configured: true,
}
const base = { card_key: 'AB-1', version: 1, created_at: 't', updated_at: 't' }

test('start the manual test, open a link, and stop the app', async ({ page }) => {
  let run: Record<string, unknown> | null = null
  let polls = 0
  const methods: string[] = []

  await page.route('**/api/cards', (route) => route.fulfill({ json: [card] }))
  await page.route('**/api/cards/AB-1', (route) => route.fulfill({ json: card }))
  await page.route('**/api/ai-config', (route) =>
    route.fulfill({ json: { eligible_statuses: ['DEV In Progress'], project_repos: { AB: '/r' } } }),
  )
  await page.route('**/api/plans', (route) => route.fulfill({ json: { 'AB-1': 'approved' } }))
  await page.route('**/api/implementations', (route) => route.fulfill({ json: { 'AB-1': 'completed' } }))
  await page.route('**/api/reviews', (route) => route.fulfill({ json: { 'AB-1': 'clean' } }))
  await page.route('**/api/tests', (route) => route.fulfill({ json: run ? { 'AB-1': run.state } : {} }))
  await page.route('**/api/cards/AB-1/plan', (route) =>
    route.fulfill({
      json: { ...base, state: 'approved', plan: '1. Do it', error: null, history: [], feedback: null },
    }),
  )
  await page.route('**/api/cards/AB-1/implementation', (route) =>
    route.fulfill({
      json: {
        ...base, plan_version: 1, state: 'completed', stage: 'done', branch: 'AB-1_x', base_branch: 'main',
        base_commit: 'abc', commits: [], notes: [], report: null, error: null,
      },
    }),
  )
  await page.route('**/api/cards/AB-1/review', (route) =>
    route.fulfill({
      json: {
        ...base, implementation_version: 1, state: 'clean', branch: 'AB-1_x', base_commit: 'abc',
        head_before: 'def', fix_commits: [], notes: [], report: null, error: null,
      },
    }),
  )
  await page.route('**/api/cards/AB-1/test', (route) => {
    const method = route.request().method()
    methods.push(method)
    const running = {
      ...base, review_version: 1, branch: 'AB-1_x', apps: [
        { name: 'api', start_command: 'npm start', workdir: 'server', ready_url: 'http://localhost:8000/' },
        { name: 'web', start_command: 'npm run dev', workdir: '.', ready_url: 'http://localhost:5173/' },
      ],
      notes: [], report: 'Dark mode added', error: null,
      links: [{ title: 'Settings page', url: 'http://localhost:5173/settings', check: 'Toggle dark mode' }],
    }
    if (method === 'POST') {
      polls = 0
      run = { ...running, state: 'preparing', links: [], report: null }
      return route.fulfill({ status: 202, json: run })
    }
    if (method === 'DELETE') {
      run = { ...running, state: 'stopped' }
      return route.fulfill({ json: run })
    }
    if (!run) return route.fulfill({ status: 404, json: { detail: 'No test run exists for this card' } })
    if (run.state === 'preparing' && ++polls >= 2) run = { ...running, state: 'running' }
    return route.fulfill({ json: run })
  })

  await page.goto('/')
  await expect(page.getByText('Test: available')).toBeVisible()
  await page.goto('/cards/AB-1')
  await page.getByRole('button', { name: /^Test not started/ }).click()
  await page.getByRole('button', { name: 'Start test', exact: true }).click()
  await expect(page.getByText(/Working out how to run the app/)).toBeVisible()

  const link = page.getByRole('link', { name: 'Settings page' })
  await expect(link).toHaveAttribute('href', 'http://localhost:5173/settings', { timeout: 15_000 })
  await expect(link).toHaveAttribute('target', '_blank')
  await expect(page.getByText('Toggle dark mode')).toBeVisible()
  await expect(page.getByRole('list', { name: 'Running apps' })).toContainText('api')
  await expect(page.getByRole('list', { name: 'Running apps' })).toContainText('web')

  await page.getByRole('button', { name: 'Stop app' }).click()
  await expect(page.getByRole('button', { name: 'Test again', exact: true })).toBeEnabled()
  await expect(link).toHaveCount(0)
  expect(methods).toContain('DELETE')
})
