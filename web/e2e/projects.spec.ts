import { expect, test, type Page } from '@playwright/test'

interface Stored {
  key: string
  name: string
  repo_path: string
  jira: boolean
  provider: string | null
  path: string | null
}

const toProject = (p: Stored, cards: unknown[] | null = null) => ({
  key: p.key,
  name: p.name,
  repo_path: p.repo_path,
  repo_exists: true,
  jira: p.jira,
  host: { project: p.key, repo: p.repo_path, provider: p.provider, path: p.path, source: p.path ? 'override' : null, detected: null },
  jira_connected: true,
  gitlab_connected: false,
  github_connected: true,
  test_apps_configured: false,
  status: [
    { id: 'repo', label: 'Local repo found', done: true },
    { id: 'tests', label: 'Test apps set', done: false },
  ],
  cards,
  card_warnings: null,
})

const CARD = {
  key: 'AB-1',
  summary: 'First card',
  status: 'To Do',
  source: 'jira',
  url: 'u',
  eligible: true,
  plan_state: null,
  implementation_state: null,
  review_state: null,
  test_state: null,
}

async function mockProjects(page: Page, store: Stored[]) {
  await page.route('**/api/projects', async (route) => {
    if (route.request().method() === 'POST') {
      const b = route.request().postDataJSON()
      const github = !b.jira_enabled
      const p: Stored = {
        key: github ? 'GH_' + b.host_path.split('/')[1].toUpperCase() : b.key,
        name: b.name,
        repo_path: b.repo_path,
        jira: b.jira_enabled,
        provider: b.provider,
        path: b.host_path,
      }
      store.push(p)
      return route.fulfill({ status: 201, json: toProject(p) })
    }
    return route.fulfill({ json: store.map((p) => toProject(p)) })
  })
  await page.route('**/api/projects/*', async (route) => {
    const key = route.request().url().split('/').pop()!
    const i = store.findIndex((p) => p.key === key)
    const method = route.request().method()
    if (method === 'DELETE') {
      store.splice(i, 1)
      return route.fulfill({ status: 204 })
    }
    if (method === 'PUT') {
      const b = route.request().postDataJSON()
      store[i] = { ...store[i], name: b.name, repo_path: b.repo_path, provider: b.provider, path: b.host_path }
      return route.fulfill({ json: toProject(store[i]) })
    }
    return route.fulfill({ json: toProject(store[i], key === 'AB' ? [CARD] : []) })
  })
}

test('add a Jira + GitHub project and a GitHub-only project, edit and delete', async ({ page }) => {
  const store: Stored[] = []
  await mockProjects(page, store)
  await page.goto('/projects')
  await expect(page.getByText('No projects yet')).toBeVisible()

  await page.getByRole('button', { name: 'Add project' }).click()
  let dialog = page.getByRole('dialog')
  await dialog.getByLabel('Project name').fill('Alpha')
  await dialog.getByRole('combobox', { name: 'Type' }).click()
  await page.getByRole('option', { name: 'Jira + GitHub' }).click()
  await dialog.getByLabel('Jira project key').fill('ab')
  await dialog.getByLabel('Repo path').fill('/repos/alpha')
  await dialog.getByLabel('GitHub project path').fill('me/alpha')
  await dialog.getByRole('button', { name: 'Create' }).click()
  await expect(page.getByRole('list', { name: 'Setup checklist' })).toBeVisible()
  expect(store[0]).toMatchObject({ key: 'AB', provider: 'github', path: 'me/alpha', jira: true })

  await page.getByRole('button', { name: 'Add project' }).click()
  dialog = page.getByRole('dialog')
  await dialog.getByLabel('Project name').fill('Beta')
  await dialog.getByRole('combobox', { name: 'Type' }).click()
  await page.getByRole('option', { name: 'GitHub only' }).click()
  await expect(dialog.getByLabel('Jira project key')).toHaveCount(0)
  await dialog.getByLabel('Repo path').fill('/repos/beta')
  await dialog.getByLabel('GitHub project path').fill('me/beta')
  await dialog.getByRole('button', { name: 'Create' }).click()
  await expect(page.getByRole('button', { name: /Beta/ })).toBeVisible()
  expect(store[1]).toMatchObject({ key: 'GH_BETA', jira: false })

  await page.getByRole('button', { name: 'Edit' }).click()
  dialog = page.getByRole('dialog')
  await dialog.getByLabel('Project name').fill('Beta 2')
  await dialog.getByRole('button', { name: 'Save' }).click()
  await expect(page.getByRole('button', { name: /Beta 2/ })).toBeVisible()
  expect(store[1].name).toBe('Beta 2')

  await page.getByRole('button', { name: 'Delete' }).click()
  await page.getByRole('button', { name: 'Confirm delete' }).click()
  await expect(page.getByRole('button', { name: /Beta 2/ })).toHaveCount(0)
  expect(store.map((p) => p.key)).toEqual(['AB'])
})

test('expand a project, see its cards and open one', async ({ page }) => {
  const store: Stored[] = [
    { key: 'AB', name: 'Alpha', repo_path: '/repos/alpha', jira: true, provider: 'github', path: 'me/alpha' },
  ]
  await mockProjects(page, store)
  await page.route('**/api/cards/AB-1**', (route) =>
    route.fulfill({ status: 404, json: { detail: 'Card AB-1 not found' } }),
  )
  await page.goto('/projects')
  await page.getByRole('button', { name: /Alpha/ }).click()
  await expect(page.getByText('First card')).toBeVisible()
  await expect(page.getByText('No plan')).toBeVisible()
  await page.getByRole('link', { name: 'AB-1' }).click()
  await expect(page).toHaveURL(/\/cards\/AB-1$/)
})
