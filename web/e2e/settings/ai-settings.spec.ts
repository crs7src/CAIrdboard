import { expect, test } from '@playwright/test'

test('edit AI settings and save them', async ({ page }) => {
  let saved: unknown = null
  await page.route('**/api/fs/dirs*', (route) => {
    const path = new URL(route.request().url()).searchParams.get('path')
    return route.fulfill({
      json:
        path === '/home/me/repos'
          ? { path: '/home/me/repos', parent: '/home/me', dirs: [{ name: 'xy', is_git: true }] }
          : path === '/home/me/repos/xy'
            ? { path: '/home/me/repos/xy', parent: '/home/me/repos', dirs: [] }
            : { path: '/home/me', parent: '/home', dirs: [{ name: 'repos', is_git: false }] },
    })
  })
  const cards = ['AB', 'XY'].map((project) => ({
    key: `${project}-1`, summary: 's', status: 'To Do', priority: null, url: 'u', project, description: '',
  }))
  await page.route('**/api/cards', (route) => route.fulfill({ json: cards }))
  await page.route('**/api/ai-config', (route) => {
    if (route.request().method() === 'PUT') {
      saved = route.request().postDataJSON()
      return route.fulfill({ json: saved })
    }
    return route.fulfill({
      json: { eligible_statuses: ['Backlog'], project_repos: { AB: '/repos/ab' }, auto_review: true },
    })
  })
  await page.goto('/')
  await page.getByRole('link', { name: 'Settings', exact: true }).click()
  await page.getByRole('tab', { name: 'AI', exact: true }).click()
  await expect(page.getByLabel('Eligible Jira statuses')).toHaveValue('Backlog')
  await page.getByLabel('Eligible Jira statuses').fill('Backlog, Ready to Play')
  await page.getByRole('button', { name: 'Add project' }).click()
  await page.getByLabel('Project key 2').click()
  await expect(page.getByRole('option')).toHaveText(['XY'])
  await page.getByRole('option', { name: 'XY' }).click()
  await page.getByRole('button', { name: 'Browse for repo 2' }).click()
  await page.getByText('repos', { exact: true }).click()
  await page.getByText('xy', { exact: true }).click()
  await page.getByRole('button', { name: 'Select this folder' }).click()
  await expect(page.getByLabel('Repo path 2')).toHaveValue('/home/me/repos/xy')
  await page.getByLabel('Automatically start the review when implementation completes').uncheck()
  await page.getByRole('button', { name: 'Save AI settings' }).click()

  await expect(page.getByRole('status')).toHaveText('AI settings saved.')
  expect(saved).toEqual({
    eligible_statuses: ['Backlog', 'Ready to Play'],
    project_repos: { AB: '/repos/ab', XY: '/home/me/repos/xy' },
    auto_review: false,
  })
})
