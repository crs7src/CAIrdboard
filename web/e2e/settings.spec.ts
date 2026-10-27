import { expect, test } from '@playwright/test'

const empty = { configured: false, connected: false, user: null, base_url: '', email: '' }

test('user can set up Jira credentials from Settings', async ({ page }) => {
  let saved: unknown = null
  await page.route('**/api/jira/status', (route) =>
    route.fulfill({
      json: saved
        ? { configured: true, connected: true, user: 'Me', base_url: 'https://a.atlassian.net', email: 'me@x.com' }
        : empty,
    }),
  )
  await page.route('**/api/jira/credentials', (route) => {
    saved = route.request().postDataJSON()
    return route.fulfill({ json: { connected: true, user: 'Me' } })
  })

  await page.goto('/')
  await page.getByRole('link', { name: 'Settings', exact: true }).click()
  await page.getByLabel('Jira site URL').fill('https://a.atlassian.net')
  await page.getByLabel('Jira email').fill('me@x.com')
  await page.getByLabel('Jira API token').fill('my-secret')
  await page.getByRole('button', { name: 'Save' }).click()

  await expect(page.getByRole('status')).toHaveText('Saved. Connected as Me.')
  await expect(page.getByText('Connected to Jira as Me.')).toBeVisible()
  expect(saved).toEqual({ base_url: 'https://a.atlassian.net', email: 'me@x.com', token: 'my-secret' })
  await expect(page.getByLabel('Jira API token')).toHaveValue('')
  await expect(page.getByLabel('Jira email')).toHaveValue('me@x.com')
})

test('rejected credentials show an error', async ({ page }) => {
  await page.route('**/api/jira/status', (route) => route.fulfill({ json: empty }))
  await page.route('**/api/jira/credentials', (route) =>
    route.fulfill({ status: 400, json: { detail: 'Jira did not accept these credentials: Jira returned 401' } }),
  )
  await page.goto('/settings')
  await page.getByLabel('Jira site URL').fill('https://a.atlassian.net')
  await page.getByLabel('Jira email').fill('me@x.com')
  await page.getByLabel('Jira API token').fill('bad')
  await page.getByRole('button', { name: 'Save' }).click()
  await expect(page.getByRole('alert')).toContainText('did not accept')
})
