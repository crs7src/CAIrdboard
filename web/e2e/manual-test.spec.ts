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
  await page.route('**/api/test-configs', (route) => route.fulfill({ json: [] }))
  // The AI's result is saved once the app has run.
  await page.route('**/api/cards/AB-1/test/config', (route) =>
    run && run.state !== 'preparing'
      ? route.fulfill({ json: { project: 'AB', apps: run.apps, saved_from: 'AB-1', saved_at: 'now' } })
      : route.fulfill({ status: 404, json: { detail: 'none' } }),
  )
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

  let approved = false
  await page.route('**/api/merge-requests', (route) => route.fulfill({ json: {} }))
  await page.route('**/api/cards/AB-1/merge-request', (route) =>
    route.fulfill({ status: 404, json: { detail: 'none' } }),
  )
  await page.route('**/api/test-approvals', (route) => route.fulfill({ json: approved ? ['AB-1'] : [] }))
  await page.route('**/api/cards/AB-1/test/approval', (route) => {
    if (route.request().method() === 'PUT') approved = true
    if (route.request().method() === 'DELETE') approved = false
    return route.fulfill({ json: { approved, approved_at: approved ? 't' : null } })
  })

  await page.goto('/')
  await expect(page.getByText('Test: available')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Test', exact: true })).toBeDisabled()
  await page.goto('/cards/AB-1')
  await page.getByRole('button', { name: /^Test not started/ }).click()
  await expect(page.getByRole('button', { name: 'Start test', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: 'Start with AI' }).click()
  await expect(page.getByText(/Working out how to run the app/)).toBeVisible()

  const link = page.getByRole('link', { name: 'Settings page' })
  await expect(link).toHaveAttribute('href', 'http://localhost:5173/settings', { timeout: 15_000 })
  await expect(link).toHaveAttribute('target', '_blank')
  await expect(page.getByText('Toggle dark mode')).toBeVisible()
  await expect(page.getByRole('list', { name: 'Running apps' })).toContainText('api')
  await expect(page.getByRole('list', { name: 'Running apps' })).toContainText('web')

  await page.getByRole('button', { name: 'Approve', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Approved', exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'Back to Home' }).click()
  await expect(page.getByText('Test: approved')).toBeVisible()
  await expect(page.getByRole('img', { name: 'Test' })).toBeVisible()

  // a later change to the branch (auto or manual review) withdraws the approval on the server
  approved = false
  await page.goto('/cards/AB-1')
  await page.getByRole('button', { name: /^Test/ }).first().click()
  await expect(page.getByRole('button', { name: 'Approve', exact: true })).toBeVisible()

  await page.getByRole('button', { name: 'Stop app' }).click()
  await expect(page.getByRole('button', { name: 'Test again', exact: true })).toBeEnabled()
  await expect(link).toHaveCount(0)
  expect(methods).toContain('DELETE')

  await page.getByRole('link', { name: 'Settings → Test apps' }).click()
  await expect(page).toHaveURL(/\/settings\/test-apps/)
})

test('saved settings are used, and a problem report restarts with the fix', async ({ page }) => {
  let run: Record<string, unknown> | null = null
  let config: Record<string, unknown> | null = {
    project: 'AB',
    apps: [{ name: 'web', start_command: 'npm run dev', workdir: '.', ready_url: 'http://localhost:5173/' }],
    saved_from: 'AB-0',
    saved_at: 't',
  }
  const posts: { url: string; body: unknown }[] = []
  const attempt = (over: Record<string, unknown>) => ({
    ...base, review_version: 1, branch: 'AB-1_x', notes: [], report: null, error: null, problem: null,
    apps: (config?.apps as unknown[]) ?? [],
    links: [{ title: 'Web app', url: 'http://localhost:5173/', check: '' }],
    ...over,
  })

  await page.route('**/api/cards', (route) => route.fulfill({ json: [card] }))
  await page.route('**/api/cards/AB-1', (route) => route.fulfill({ json: card }))
  await page.route('**/api/ai-config', (route) =>
    route.fulfill({ json: { eligible_statuses: ['DEV In Progress'], project_repos: { AB: '/r' } } }),
  )
  await page.route('**/api/plans', (route) => route.fulfill({ json: { 'AB-1': 'approved' } }))
  await page.route('**/api/implementations', (route) => route.fulfill({ json: { 'AB-1': 'completed' } }))
  await page.route('**/api/reviews', (route) => route.fulfill({ json: { 'AB-1': 'clean' } }))
  await page.route('**/api/tests', (route) => route.fulfill({ json: run ? { 'AB-1': run.state } : {} }))
  await page.route('**/api/test-configs', (route) => route.fulfill({ json: ['AB'] }))
  await page.route('**/api/cards/AB-1/plan', (route) =>
    route.fulfill({ json: { ...base, state: 'approved', plan: '1. Do it', error: null, history: [], feedback: null } }),
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
  await page.route('**/api/cards/AB-1/test/config', (route) => {
    if (route.request().method() === 'DELETE') {
      config = null
      return route.fulfill({ status: 204 })
    }
    return config
      ? route.fulfill({ json: config })
      : route.fulfill({ status: 404, json: { detail: 'No saved test settings' } })
  })
  await page.route('**/api/cards/AB-1/test/problem', (route) => {
    posts.push({ url: 'problem', body: route.request().postDataJSON() })
    run = attempt({ version: 2, state: 'running', source: 'feedback', problem: 'login is blank' })
    return route.fulfill({ status: 202, json: { ...run, state: 'preparing' } })
  })
  await page.route('**/api/cards/AB-1/test', (route) => {
    const method = route.request().method()
    if (method === 'POST') {
      posts.push({ url: 'start', body: route.request().postDataJSON() })
      run = attempt({ state: 'running', source: 'saved', notes: ["Started with the project's saved settings (no AI used)."] })
      return route.fulfill({ status: 202, json: { ...run, state: 'preparing' } })
    }
    if (method === 'DELETE') return route.fulfill({ json: { ...run, state: 'stopped' } })
    return run
      ? route.fulfill({ json: run })
      : route.fulfill({ status: 404, json: { detail: 'No test run exists for this card' } })
  })

  await page.route('**/api/merge-requests', (route) => route.fulfill({ json: {} }))
  await page.route('**/api/cards/AB-1/merge-request', (route) =>
    route.fulfill({ status: 404, json: { detail: 'none' } }),
  )
  let approved = false
  await page.route('**/api/test-approvals', (route) => route.fulfill({ json: approved ? ['AB-1'] : [] }))
  await page.route('**/api/cards/AB-1/test/approval', (route) => {
    if (route.request().method() === 'PUT') approved = true
    if (route.request().method() === 'DELETE') approved = false
    return route.fulfill({ json: { approved, approved_at: approved ? 't' : null } })
  })

  await page.goto('/cards/AB-1')
  await page.getByRole('button', { name: /^Test not started/ }).click()
  await expect(page.getByText('saved settings', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Start test', exact: true }).click()
  await expect(page.getByRole('link', { name: 'Web app' })).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText(/saved settings \(no AI used\)/)).toBeVisible()
  expect(posts[0]).toEqual({ url: 'start', body: null })

  await page.getByLabel('Describe what is not running right').fill('login is blank')
  await page.getByRole('button', { name: 'Send problem report' }).click()
  await expect(page.getByText('Reported problem: login is blank')).toBeVisible({ timeout: 15_000 })
  expect(posts[1]).toEqual({ url: 'problem', body: { message: 'login is blank' } })

  await page.getByRole('button', { name: 'Forget saved settings' }).click()
  await expect(page.getByText('saved settings', { exact: true })).toHaveCount(0)
})
