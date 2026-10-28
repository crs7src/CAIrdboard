import { expect, test } from '@playwright/test'

test('connect GitHub and map and check a repository under Settings', async ({ page }) => {
  let status = { configured: false, connected: false, user: null as string | null, url: '' }
  let override: string | null = null
  const info = () => ({
    project: 'AB',
    repo: '/repo',
    provider: 'github',
    path: override ?? 'you/app',
    source: override ? 'override' : 'origin',
    detected: { provider: 'github', path: 'you/app' },
  })
  await page.route('**/api/github/status', (route) => route.fulfill({ json: status }))
  await page.route('**/api/github/credentials', (route) => {
    const body = route.request().postDataJSON()
    status = { configured: true, connected: true, user: 'Me', url: body.url }
    return route.fulfill({ json: { connected: true, user: 'Me' } })
  })
  await page.route('**/api/repo-hosts', (route) => route.fulfill({ json: [info()] }))
  await page.route('**/api/repo-hosts/AB', (route) => {
    override = route.request().method() === 'PUT' ? route.request().postDataJSON().path : null
    return route.fulfill({ json: info() })
  })
  await page.route('**/api/repo-hosts/AB/check', (route) =>
    route.fulfill({
      json: { provider: 'github', path: info().path, web_url: 'u', default_branch: 'main' },
    }),
  )

  await page.goto('/settings')
  await page.getByRole('tab', { name: 'GitHub' }).click()
  await page.getByLabel('GitHub URL').fill('https://api.github.com')
  await page.getByLabel('GitHub access token').fill('tok')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByText('Saved. Connected as Me.')).toBeVisible()

  const row = page.getByRole('group', { name: 'GitHub project AB' })
  await expect(row.getByText('Using you/app (from origin remote)')).toBeVisible()
  await row.getByLabel('GitHub project path').fill('me/app')
  await row.getByRole('button', { name: 'Set', exact: true }).click()
  await expect(row.getByText('Using me/app (override)')).toBeVisible()
  await row.getByRole('button', { name: 'Check', exact: true }).click()
  await expect(row.getByText('OK: me/app, default branch main')).toBeVisible()
  await row.getByRole('button', { name: 'Reset', exact: true }).click()
  await expect(row.getByText('Using you/app (from origin remote)')).toBeVisible()
})
