import { expect, test } from '@playwright/test'

test('home page shows the project title and summary', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { level: 1, name: 'AI Card Board' })).toBeVisible()
  await expect(page.getByText(/Review the Jira cards assigned to you/)).toBeVisible()
})
