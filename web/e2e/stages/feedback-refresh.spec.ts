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
const base = { card_key: 'AB-1', created_at: 't', updated_at: 't' }

test('sending test issues turns the card back to implementation, then review, without a reload', async ({
  page,
}) => {
  let phase: 'idle' | 'fixing' | 'fixed' | 'reviewing' | 'clean' = 'idle'
  const impl = (state: string, stage: string) => ({
    ...base, version: 1, plan_version: 1, state, stage, branch: 'AB-1_x', base_branch: 'main',
    base_commit: 'abc', commits: [], notes: [], report: null, error: null,
  })
  const rev = (version: number, state: string) => ({
    ...base, version, implementation_version: 1, state, branch: 'AB-1_x', base_commit: 'abc',
    head_before: 'def', fix_commits: [], notes: [], report: null, error: null,
  })
  const fixRun = (state: string) => ({
    ...base, version: 1, implementation_version: 1, state, branch: 'AB-1_x', base_commit: 'abc',
    commits: [], comment_ids: [], report: null, error: null,
  })

  await page.route('**/api/cards/AB-1', (route) => route.fulfill({ json: card }))
  await page.route('**/api/cards/AB-1/plan', (route) =>
    route.fulfill({
      json: { ...base, version: 1, state: 'approved', plan: '1. Do it', error: null, history: [], feedback: null },
    }),
  )
  await page.route('**/api/cards/AB-1/implementation', (route) => {
    if (phase === 'fixing') {
      phase = 'fixed'
      return route.fulfill({ json: impl('running', 'fixing') })
    }
    if (phase === 'fixed') phase = 'reviewing'
    return route.fulfill({ json: impl('completed', 'done') })
  })
  await page.route('**/api/cards/AB-1/review', (route) =>
    route.fulfill({
      json:
        phase === 'idle' || phase === 'fixing' || phase === 'fixed'
          ? rev(1, 'clean')
          : phase === 'reviewing'
            ? rev(2, 'running')
            : rev(2, 'clean'),
    }),
  )
  await page.route('**/api/cards/AB-1/test', (route) =>
    route.fulfill({ status: 404, json: { detail: 'No test run' } }),
  )
  await page.route('**/api/cards/AB-1/test/**', (route) => {
    const url = route.request().url()
    if (url.endsWith('/test/feedback') && route.request().method() === 'POST') {
      phase = 'fixing'
      return route.fulfill({ status: 202, json: fixRun('running') })
    }
    if (url.endsWith('/test/approval')) return route.fulfill({ json: { approved: false, approved_at: null } })
    return route.fulfill({ status: 404, json: { detail: 'none' } })
  })
  await page.route('**/api/cards/AB-1/feedback', (route) =>
    route.fulfill({ json: { comments: [], run: null } }),
  )
  await page.route('**/api/cards/AB-1/merge-request', (route) =>
    route.fulfill({ status: 404, json: { detail: 'none' } }),
  )
  await page.route('**/api/cards/AB-1/merge-request/**', (route) =>
    route.fulfill({ status: 404, json: { detail: 'none' } }),
  )

  await page.goto('/cards/AB-1')
  await page.getByRole('button', { name: /^Test/ }).click()
  await page.getByLabel('Issues').fill('button does nothing')
  await page.getByRole('button', { name: 'Send to code fixer' }).click()

  const reviewHeader = page.getByRole('button', { name: /^Review (running|clean|fixes made|failed)/ })
  const implementation = page.getByRole('button', { name: /^Implementation/ })
  await expect(implementation).toContainText('running')
  await expect(reviewHeader).toHaveCount(0)

  await expect(implementation).toContainText('completed', { timeout: 15000 })
  await expect(reviewHeader).toContainText('running', { timeout: 15000 })
  phase = 'clean'
  await expect(reviewHeader).toContainText('clean', { timeout: 15000 })
})
