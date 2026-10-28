import { expect, test } from '@playwright/test'

test('save an Anthropic key, and the card page shows which AI made the plan', async ({ page }) => {
  let configured = false
  const providers = () => [
    { id: 'copilot', label: 'GitHub Copilot CLI', configured: true, model: null, default_model: null, needs_key: false, supports_agent: true, is_default: true },
    { id: 'anthropic', label: 'Anthropic', configured, model: null, default_model: 'claude-sonnet-4-5', needs_key: true, supports_agent: false, is_default: false },
    { id: 'gemini', label: 'Google Gemini', configured: false, model: null, default_model: 'gemini-2.5-pro', needs_key: true, supports_agent: false, is_default: false },
  ]
  let saved: Record<string, unknown> | null = null
  await page.route('**/api/ai/providers', (route) => route.fulfill({ json: providers() }))
  await page.route('**/api/ai/providers/anthropic/credentials', (route) => {
    saved = route.request().postDataJSON()
    configured = true
    return route.fulfill({ json: providers()[1] })
  })
  await page.goto('/settings/ai-providers')
  await page.getByLabel('Anthropic API key').fill('sk-secret')
  await page.getByRole('button', { name: 'Save' }).first().click()
  await expect.poll(() => saved).toMatchObject({ api_key: 'sk-secret' })
  await expect(page.getByText('sk-secret')).toHaveCount(0)

  await page.route('**/api/cards/AB-1/**', (route) => route.fulfill({ status: 404, json: { detail: 'none' } }))
  await page.route('**/api/cards/AB-1', (route) =>
    route.fulfill({
      json: {
        key: 'AB-1', summary: 'First card', status: 'To Do', priority: null, url: 'u', project: 'AB',
        description: '', comments: [], status_history: [], reopened: false, last_reopened_at: null,
        eligible: true, repo_configured: true,
      },
    }),
  )
  await page.route('**/api/cards/AB-1/plan', (route) =>
    route.fulfill({
      json: {
        card_key: 'AB-1', version: 1, state: 'ready', jira_status: 'To Do', feedback: null,
        plan: '1. Do it', error: null, provider: 'anthropic', created_at: 't', updated_at: 't',
      },
    }),
  )
  await page.goto('/cards/AB-1')
  await expect(page.getByText('via Anthropic')).toBeVisible()
})
