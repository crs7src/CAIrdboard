import { expect, test } from '@playwright/test'

test('edit AI settings and save them', async ({ page }) => {
  let saved: unknown = null
  await page.route('**/api/ai-config', (route) => {
    if (route.request().method() === 'PUT') {
      saved = route.request().postDataJSON()
      return route.fulfill({ json: saved })
    }
    return route.fulfill({
      json: { eligible_statuses: ['Backlog'], project_repos: { AB: '/repos/ab' } },
    })
  })
  await page.goto('/')
  await page.getByRole('link', { name: 'AI Settings' }).click()
  await expect(page.getByLabel('Eligible Jira statuses')).toHaveValue('Backlog')
  await page.getByLabel('Eligible Jira statuses').fill('Backlog, Ready to Play')
  await page.getByRole('button', { name: 'Add project' }).click()
  await page.getByLabel('Project key 2').fill('xy')
  await page.getByLabel('Repo path 2').fill('/repos/xy')
  await page.getByRole('button', { name: 'Save AI settings' }).click()

  await expect(page.getByRole('status')).toHaveText('AI settings saved.')
  expect(saved).toEqual({
    eligible_statuses: ['Backlog', 'Ready to Play'],
    project_repos: { AB: '/repos/ab', xy: '/repos/xy' },
  })
})
