import { expect, test } from '@playwright/test'

test('edit, save and reset a skill under Settings', async ({ page }) => {
  let reviewer = { content: 'default reviewer', default_content: 'default reviewer', customized: false }
  const list = () => [
    { step: 'planner', content: 'p', default_content: 'p', customized: false },
    { step: 'implementer', content: 'i', default_content: 'i', customized: false },
    { step: 'reviewer', ...reviewer },
  ]
  await page.route('**/api/skills', (route) => route.fulfill({ json: list() }))
  await page.route('**/api/skills/reviewer', async (route) => {
    if (route.request().method() === 'PUT') {
      reviewer = { ...reviewer, content: route.request().postDataJSON().content, customized: true }
    } else {
      reviewer = { ...reviewer, content: reviewer.default_content, customized: false }
    }
    await route.fulfill({ json: { step: 'reviewer', ...reviewer } })
  })

  await page.goto('/settings')
  await page.getByRole('tab', { name: 'Skills' }).click()
  const header = page.getByRole('button', { name: /^Code review/ })
  await expect(header).toHaveAttribute('aria-expanded', 'false')
  await expect(header.getByText('Default', { exact: true })).toBeVisible()
  await header.click()

  await page.getByLabel('Code review skill').fill('my own reviewer')
  await page.getByRole('button', { name: 'Save' }).click()
  await expect(header.getByText('Customised')).toBeVisible()
  expect(reviewer.content).toBe('my own reviewer')

  await page.getByRole('button', { name: 'Reset to default' }).click()
  await expect(page.getByLabel('Code review skill')).toHaveValue('default reviewer')
  await expect(header.getByText('Default', { exact: true })).toBeVisible()
})
