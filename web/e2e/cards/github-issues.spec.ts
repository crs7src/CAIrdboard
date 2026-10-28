import { expect, test } from '@playwright/test'

const card = {
  key: 'GH_APP-12',
  summary: 'Fix the login bug',
  status: 'Open',
  priority: null,
  url: 'https://github.com/me/app/issues/12',
  project: 'GH_APP',
  description: 'Login fails on Safari',
  comments: [],
  status_history: [],
  reopened: false,
  last_reopened_at: null,
  source: 'github',
  external_repo: 'me/app',
}

test('a GitHub issue shows up as a card and opens its detail page', async ({ page }) => {
  await page.route('**/api/cards', (route) =>
    route.fulfill({ json: [card], headers: { 'X-Card-Warnings': 'Could not reach Jira' } }),
  )
  await page.route('**/api/ai-config', (route) =>
    route.fulfill({ json: { eligible_statuses: ['Open'], project_repos: { GH_APP: '/repo' } } }),
  )
  await page.route('**/api/cards/GH_APP-12', (route) =>
    route.fulfill({ json: { ...card, eligible: true, repo_configured: true } }),
  )
  await page.route('**/api/cards/GH_APP-12/plan', (route) =>
    route.fulfill({ status: 404, json: { detail: 'No plan exists for this card' } }),
  )

  await page.goto('/')
  await expect(page.getByRole('note')).toContainText('Could not reach Jira')
  await page.getByRole('link', { name: /GH_APP-12/ }).click()
  await expect(page.getByRole('heading', { name: 'GH_APP-12' })).toBeVisible()
  await expect(page.getByText('Login fails on Safari')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Open in GitHub' })).toHaveAttribute(
    'href',
    'https://github.com/me/app/issues/12',
  )
})
