import { expect, test } from '@playwright/test'

test('home page shows the hello message from the Python API', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Hello, world!' })).toBeVisible()
})
