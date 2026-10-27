import { expect, test } from '@playwright/test'

test('connect GitLab and map and check a project under Settings', async ({ page }) => {
  let status = { configured: false, connected: false, user: null as string | null, url: '' }
  let override: string | null = null
  const info = () => ({
    project: 'AB',
    repo: '/repo',
    detected: 'grp/app',
    override,
    effective: override ?? 'grp/app',
  })
  await page.route('**/api/gitlab/status', (route) => route.fulfill({ json: status }))
  await page.route('**/api/gitlab/credentials', (route) => {
    const body = route.request().postDataJSON()
    status = { configured: true, connected: true, user: 'Me', url: body.url }
    return route.fulfill({ json: { connected: true, user: 'Me' } })
  })
  await page.route('**/api/gitlab/projects', (route) => route.fulfill({ json: [info()] }))
  await page.route('**/api/gitlab/projects/AB', (route) => {
    override = route.request().method() === 'PUT' ? route.request().postDataJSON().path : null
    return route.fulfill({ json: info() })
  })
  await page.route('**/api/gitlab/projects/AB/check', (route) =>
    route.fulfill({
      json: { id: 1, path: info().effective, web_url: 'u', default_branch: 'main' },
    }),
  )

  await page.goto('/settings')
  await page.getByRole('tab', { name: 'GitLab' }).click()
  await page.getByLabel('GitLab URL').fill('https://git.example.com')
  await page.getByLabel('GitLab access token').fill('tok')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByText('Saved. Connected as Me.')).toBeVisible()

  const row = page.getByRole('group', { name: 'GitLab project AB' })
  await expect(row.getByText('Using grp/app (from origin remote)')).toBeVisible()
  await row.getByLabel('GitLab project path').fill('other/proj')
  await row.getByRole('button', { name: 'Set', exact: true }).click()
  await expect(row.getByText('Using other/proj (override)')).toBeVisible()
  await row.getByRole('button', { name: 'Check', exact: true }).click()
  await expect(row.getByText('OK: other/proj, default branch main')).toBeVisible()
  await row.getByRole('button', { name: 'Reset', exact: true }).click()
  await expect(row.getByText('Using grp/app (from origin remote)')).toBeVisible()
})
