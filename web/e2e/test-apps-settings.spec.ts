import { expect, test } from '@playwright/test'

test('configure how a project starts its apps under Settings', async ({ page }) => {
  let config: unknown = null
  await page.route('**/api/ai-config', (route) =>
    route.fulfill({ json: { eligible_statuses: [], project_repos: { AB: '/repo' } } }),
  )
  await page.route('**/api/test-configs/AB', async (route) => {
    const method = route.request().method()
    if (method === 'PUT') {
      config = { project: 'AB', saved_from: 'settings', saved_at: 'now', ...route.request().postDataJSON() }
      return route.fulfill({ json: config })
    }
    if (method === 'DELETE') {
      config = null
      return route.fulfill({ status: 204 })
    }
    return config ? route.fulfill({ json: config }) : route.fulfill({ status: 404, json: { detail: 'none' } })
  })

  await page.goto('/settings')
  await page.getByRole('tab', { name: 'Test apps' }).click()
  const header = page.getByRole('button', { name: /^AB/ })
  await expect(header.getByText('Not set')).toBeVisible()
  await header.click()
  await page.getByRole('button', { name: 'Add app' }).click()
  await page.getByLabel('Name', { exact: true }).fill('web')
  await page.getByLabel('Start command').fill('npm run dev')
  await page.getByLabel('Ready URL').fill('http://localhost:6001')
  await page.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(header.getByText('Configured')).toBeVisible()
  expect(config).toMatchObject({ apps: [{ name: 'web', start_command: 'npm run dev' }] })

  await page.getByRole('button', { name: 'Clear' }).click()
  await expect(header.getByText('Not set')).toBeVisible()
  expect(config).toBeNull()
})
