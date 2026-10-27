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
  let impl: Record<string, unknown> | null = null
  let implPolls = 0
  let rev: Record<string, unknown> | null = null
  let reviewPolls = 0
  const review = (over = {}) => ({
    card_key: 'AB-1',
    version: 1,
    implementation_version: 1,
    state: 'clean',
    branch: 'AB-1_add_dark_mode',
    base_commit: 'abc',
    head_before: 'def',
    fix_commits: [],
    notes: [],
    report: '## Review summary\n\nNo issues found',
    error: null,
    created_at: 't',
    updated_at: 't',
    ...over,
  })
  await page.route('**/api/cards/AB-1/review', (route) => {
    if (route.request().method() === 'POST') {
      rev = review({ state: 'running', report: null })
      reviewPolls = 0
      return route.fulfill({ status: 202, json: rev })
    }
    if (!rev) return route.fulfill({ status: 404, json: { detail: 'No review exists' } })
    if (rev.state === 'running' && ++reviewPolls >= 2) rev = review()
    return route.fulfill({ json: rev })
  })
  await page.route('**/api/cards', (route) => route.fulfill({ json: [card(cardOver)] }))
  await page.route('**/api/plans', (route) =>
    route.fulfill({ json: current ? { 'AB-1': current.state } : {} }),
  )
  await page.route('**/api/reviews', (route) =>
    route.fulfill({ json: rev ? { 'AB-1': rev.state } : {} }),
  )
  await page.route('**/api/implementations', (route) =>
    route.fulfill({ json: impl ? { 'AB-1': impl.state } : {} }),
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

  const implementation = (over = {}) => ({
    card_key: 'AB-1',
    version: 1,
    plan_version: 1,
    state: 'completed',
    stage: 'done',
    branch: 'AB-1_add_dark_mode',
    base_branch: 'main',
    base_commit: 'abc',
    commits: [
      { sha: 'aaa111', subject: 'AB-1: step 1 - add toggle' },
      { sha: 'bbb222', subject: 'AB-1: step 2 - add tests' },
    ],
    notes: [],
    report: '## Review against the plan\n\nAll steps matched',
    error: null,
    created_at: 't',
    updated_at: 't',
    ...over,
  })
  await page.route('**/api/cards/AB-1/implementation', (route) => {
    if (route.request().method() === 'POST') {
      impl = implementation({ state: 'running', stage: 'implementing', report: null, commits: [] })
      implPolls = 0
      return route.fulfill({ status: 202, json: impl })
    }
    if (!impl) return route.fulfill({ status: 404, json: { detail: 'No implementation exists' } })
    if (impl.state === 'running' && ++implPolls >= 2) impl = implementation()
    return route.fulfill({ json: impl })
  })
  return { posts }
}

test('generate, review and approve a plan for a card', async ({ page }) => {
  await mockBackend(page)
  await page.goto('/cards')
  await expect(page.getByText('Plan: available')).toBeVisible()
  // Clicking the summary text (not a link) still opens the card.
  await page.getByText('First card').click()
  await expect(page.getByRole('heading', { name: 'AB-1' })).toBeVisible()
  await expect(page.getByText('Do the first thing')).toBeVisible()
  await expect(page.getByText('Comments (1)')).toBeVisible()
  await expect(page.getByText('Fix the button color')).toBeHidden()
  await page.getByText('Comments (1)').click()
  await expect(page.getByText('Fix the button color')).toBeVisible()

  // Plan accordion starts collapsed with a play button for the next step.
  const planHeader = page.getByRole('button', { name: /^Plan/ })
  await expect(planHeader).toHaveAttribute('aria-expanded', 'false')
  await expect(page.getByText('not started')).toBeVisible()
  await page.getByRole('button', { name: 'Run plan', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Review plan', exact: true })).toBeVisible({ timeout: 10_000 })

  // Play on a ready plan opens the accordion and focuses Approve.
  await page.getByRole('button', { name: 'Review plan', exact: true }).click()
  await expect(planHeader).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByRole('heading', { name: 'Steps' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Approve', exact: true })).toBeFocused()

  await page.getByRole('button', { name: 'Approve', exact: true }).click()
  await expect(page.getByText('approved', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Approve', exact: true })).toHaveCount(0)

  await page.goto('/cards')
  await expect(page.getByText('Implementation: available')).toBeVisible()
  await expect(page.getByRole('img', { name: 'Plan' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Implement' })).toBeEnabled()
  await expect(page.getByRole('button', { name: 'Review' })).toBeDisabled()
})

test('plan and implement can be started from the cards list', async ({ page }) => {
  await mockBackend(page)
  await page.goto('/cards')
  await expect(page.getByRole('button', { name: 'Implement' })).toBeDisabled()
  await page.getByRole('button', { name: 'Plan' }).click()
  await expect(page).toHaveURL(/\/cards$/)
  await expect(page.getByText('Plan: running')).toBeVisible()
})

test('approved plan can be implemented on a new branch with a review report', async ({ page }) => {
  await mockBackend(page)
  await page.goto('/cards/AB-1')
  await expect(page.getByRole('button', { name: 'Start implementation', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Run plan', exact: true }).click()
  await page.getByRole('button', { name: 'Review plan', exact: true }).click()
  await page.getByRole('button', { name: 'Approve', exact: true }).click()

  await page.getByRole('button', { name: 'Start implementation', exact: true }).click()
  await page.getByRole('button', { name: /^Implementation/ }).click()
  await expect(page.getByText('Implementing...')).toBeVisible()
  await expect(page.getByText('AB-1: step 2 - add tests')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText('AB-1_add_dark_mode')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Review against the plan' })).toBeVisible()
  await expect(page.getByText('completed', { exact: true })).toBeVisible()
})

test('reject a plan and regenerate it with feedback', async ({ page }) => {
  const { posts } = await mockBackend(page)
  await page.goto('/cards/AB-1')
  await page.getByRole('button', { name: 'Run plan', exact: true }).click()
  await page.getByRole('button', { name: 'Review plan', exact: true }).click()
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
  await expect(page.getByRole('button', { name: /Generate plan|Run plan/ })).toHaveCount(0)
})

test('back button returns to My Cards', async ({ page }) => {
  await mockBackend(page)
  await page.goto('/cards/AB-1')
  await page.getByRole('link', { name: 'Back to My Cards' }).click()
  await expect(page).toHaveURL(/\/cards$/)
  await expect(page.getByRole('heading', { name: 'My Cards' })).toBeVisible()
})

test('Plan button on My Cards opens a ready plan expanded', async ({ page }) => {
  await mockBackend(page)
  await page.goto('/cards/AB-1')
  await page.getByRole('button', { name: 'Run plan', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Review plan', exact: true })).toBeVisible({ timeout: 10_000 })
  await page.getByRole('link', { name: 'Back to My Cards' }).click()
  await page.getByRole('button', { name: 'Plan', exact: true }).click()
  await expect(page).toHaveURL(/open=plan/)
  await expect(page.getByRole('button', { name: 'Approve', exact: true })).toBeVisible()
})

test('a completed implementation can be reviewed from the card and the list', async ({ page }) => {
  await mockBackend(page)
  await page.goto('/cards/AB-1')
  await page.getByRole('button', { name: 'Run plan', exact: true }).click()
  await page.getByRole('button', { name: 'Review plan', exact: true }).click()
  await page.getByRole('button', { name: 'Approve', exact: true }).click()
  await page.getByRole('button', { name: 'Start implementation', exact: true }).click()

  await page.getByRole('button', { name: 'Start review', exact: true }).click({ timeout: 15_000 })
  await page.getByRole('button', { name: /^Review clean/ }).click({ timeout: 15_000 })
  await expect(page.getByRole('heading', { name: 'Review summary' })).toBeVisible()

  await page.getByRole('link', { name: 'Back to My Cards' }).click()
  await expect(page.getByText('Review: clean')).toBeVisible()
  await expect(page.getByRole('img', { name: 'Review', exact: true })).toBeVisible()
})

test('changes page shows the branch diff file by file', async ({ page }) => {
  await mockBackend(page)
  const diff = [
    'diff --git a/src/a.ts b/src/a.ts',
    '--- a/src/a.ts',
    '+++ b/src/a.ts',
    '@@ -1,2 +1,2 @@',
    ' keep',
    '-old line',
    '+new line',
    'diff --git a/src/b.ts b/src/b.ts',
    'new file mode 100644',
    '--- /dev/null',
    '+++ b/src/b.ts',
    '@@ -0,0 +1 @@',
    '+brand new',
    '',
  ].join('\n')
  const commits = [{ sha: 'aaaaaaa1', short: 'aaaaaaa', subject: 'AB-1: step 1 - add toggle' }]
  await page.route('**/api/cards/AB-1/changes**', (route) =>
    route.fulfill({
      json: { branch: 'AB-1_add_dark_mode', base_commit: 'abc', commits, selected_commit: null, diff },
    }),
  )
  await page.goto('/cards/AB-1')
  await page.getByRole('button', { name: 'Run plan', exact: true }).click()
  await page.getByRole('button', { name: 'Review plan', exact: true }).click()
  await page.getByRole('button', { name: 'Approve', exact: true }).click()
  await page.getByRole('button', { name: 'Start implementation', exact: true }).click()
  await page.getByRole('link', { name: 'View changes' }).click({ timeout: 15_000 })

  await expect(page).toHaveURL(/\/cards\/AB-1\/changes$/)
  await expect(page.getByText('2 files changed,')).toBeVisible()
  await expect(page.getByText('new line')).toBeVisible()
  await expect(page.getByText('brand new')).toBeHidden()
  await page.getByRole('list', { name: 'Changed files' }).getByText('src/b.ts').click()
  await expect(page.getByText('brand new')).toBeVisible()
  await expect(page.getByText('new line')).toBeHidden()
  const main = await page.locator('main').boundingBox()
  expect(main!.width).toBeGreaterThan(1200)
  // The page itself does not scroll; only the diff pane does.
  expect(await page.evaluate(() => document.documentElement.scrollHeight <= window.innerHeight)).toBe(true)
  await page.getByRole('link', { name: 'Back to AB-1' }).click()
  await expect(page.getByRole('heading', { name: 'AB-1', exact: true })).toBeVisible()
})
