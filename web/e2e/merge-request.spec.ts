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
const MR_URL = 'https://git.example.com/grp/app/-/merge_requests/42'

test('approve the test, create the merge request and follow its link', async ({ page }) => {
  let approved = false
  let mr: Record<string, unknown> | null = null
  let polls = 0

  await page.route('**/api/cards', (route) => route.fulfill({ json: [card] }))
  await page.route('**/api/cards/AB-1', (route) => route.fulfill({ json: card }))
  await page.route('**/api/ai-config', (route) =>
    route.fulfill({ json: { eligible_statuses: ['DEV In Progress'], project_repos: { AB: '/r' } } }),
  )
  await page.route('**/api/plans', (route) => route.fulfill({ json: { 'AB-1': 'approved' } }))
  await page.route('**/api/implementations', (route) => route.fulfill({ json: { 'AB-1': 'completed' } }))
  await page.route('**/api/reviews', (route) => route.fulfill({ json: { 'AB-1': 'clean' } }))
  await page.route('**/api/tests', (route) => route.fulfill({ json: { 'AB-1': 'stopped' } }))
  await page.route('**/api/test-configs', (route) => route.fulfill({ json: ['AB'] }))
  await page.route('**/api/test-approvals', (route) => route.fulfill({ json: approved ? ['AB-1'] : [] }))
  await page.route('**/api/cards/AB-1/test/config', (route) =>
    route.fulfill({ status: 404, json: { detail: 'none' } }),
  )
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
  await page.route('**/api/cards/AB-1/test', (route) =>
    route.fulfill({
      json: {
        ...base, review_version: 1, state: 'stopped', source: 'saved', problem: null, branch: 'AB-1_x',
        apps: [], links: [], notes: [], report: null, error: null,
      },
    }),
  )
  await page.route('**/api/cards/AB-1/test/approval', (route) => {
    if (route.request().method() === 'PUT') approved = true
    if (route.request().method() === 'DELETE') approved = false
    return route.fulfill({ json: { approved, approved_at: approved ? 't' : null } })
  })
  const mrRun = (state: string) => ({
    ...base, state, branch: 'AB-1_x', target_branch: 'main', title: 'AB-1 x', gitlab_project: 'grp/app',
    mr_iid: state === 'created' ? 42 : null, mr_url: state === 'created' ? MR_URL : null,
    updated_existing: false, outdated: false, error: null,
  })
  await page.route('**/api/merge-requests', (route) =>
    route.fulfill({ json: mr ? { 'AB-1': mr.state } : {} }),
  )
  await page.route('**/api/cards/AB-1/merge-request', (route) => {
    if (route.request().method() === 'POST') {
      polls = 0
      mr = mrRun('running')
      return route.fulfill({ status: 202, json: mr })
    }
    if (!mr) return route.fulfill({ status: 404, json: { detail: 'none' } })
    if (mr.state === 'running' && ++polls >= 1) mr = mrRun('created')
    return route.fulfill({ json: mr })
  })

  await page.goto('/')
  await expect(page.getByRole('button', { name: 'Create MR', exact: true })).toBeDisabled()

  await page.goto('/cards/AB-1')
  await expect(page.getByRole('button', { name: /^Merge request/ })).toHaveCount(0)
  await page.getByRole('button', { name: /^Test stopped/ }).click()
  await page.getByRole('button', { name: 'Approve', exact: true }).click()

  await page.getByRole('button', { name: 'Create merge request', exact: true }).click()
  const link = page.getByRole('link', { name: '!42 AB-1 x' })
  await expect(link).toHaveAttribute('href', MR_URL)
  await expect(page.getByText('created', { exact: true })).toBeVisible()

  await page.goto('/')
  await expect(page.getByRole('img', { name: 'Create MR' })).toBeVisible()
})
