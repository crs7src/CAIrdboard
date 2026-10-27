import { expect, test } from '@playwright/test'

test('home page shows the title and no summary', async ({ page }) => {
  await page.route('**/api/cards', (route) => route.fulfill({ json: [] }))
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: 'CAIrdboard' })).toBeVisible()
  await expect(page.getByText(/Review the Jira cards assigned to you/)).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'My Cards' })).toHaveCount(0)
})
