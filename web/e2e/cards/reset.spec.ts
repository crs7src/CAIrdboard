import { expect, test, type Page } from '@playwright/test'

const card = (over = {}) => ({
  key: 'AB-1', summary: 'First card', status: 'Reopened', priority: null,
  url: 'https://x.atlassian.net/browse/AB-1', project: 'AB', description: 'Do it',
  comments: [], status_history: [], reopened: true, last_reopened_at: '2026-02-01T10:00:00.000+0000',
  eligible: true, repo_configured: true, reset_needed: false, ...over,
})

async function mockBackend(page: Page, resetNeeded: boolean) {
  const calls: string[] = []
  let needed = resetNeeded
  await page.route('**/api/cards/AB-1', (route) =>
    route.fulfill({ json: card({ reset_needed: needed }) }),
  )
  await page.route('**/api/cards/AB-1/plan', (route) =>
    route.fulfill({ status: 404, json: { detail: 'No plan exists for this card' } }),
  )
  await page.route('**/api/cards/AB-1/reset', (route) => {
    calls.push(`reset ${route.request().postData()}`)
    needed = false
    return route.fulfill({ json: { branch: 'AB-1_x', branch_deleted: true, deleted_sha: 'abc', notes: [] } })
  })
  await page.route('**/api/cards/AB-1/reopen-prompt/dismiss', (route) => {
    calls.push('dismiss')
    needed = false
    return route.fulfill({ status: 204 })
  })
  return calls
}

test('reopen prompt: Yes resets the card', async ({ page }) => {
  const calls = await mockBackend(page, true)
  await page.goto('/cards/AB-1')
  await expect(page.getByRole('note').filter({ hasText: 'has been reopened' })).toBeVisible()
  await page.getByRole('button', { name: 'Yes' }).click()
  await expect(page.getByRole('note').filter({ hasText: 'has been reopened' })).toHaveCount(0)
  expect(calls).toEqual(['reset {"delete_branch":true}'])
})

test('reopen prompt: No dismisses it without resetting', async ({ page }) => {
  const calls = await mockBackend(page, true)
  await page.goto('/cards/AB-1')
  await page.getByRole('button', { name: 'No', exact: true }).click()
  await expect(page.getByRole('note').filter({ hasText: 'has been reopened' })).toHaveCount(0)
  expect(calls).toEqual(['dismiss'])
})

test('Reset card button asks for confirmation before resetting', async ({ page }) => {
  const calls = await mockBackend(page, false)
  await page.goto('/cards/AB-1')
  await expect(page.getByRole('note').filter({ hasText: 'has been reopened' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Reset card' }).click()
  await page.getByRole('button', { name: 'Cancel' }).click()
  expect(calls).toEqual([])
  await page.getByRole('button', { name: 'Reset card' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Reset', exact: true }).click()
  await expect.poll(() => calls).toEqual(['reset {"delete_branch":true}'])
})
