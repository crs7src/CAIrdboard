import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { mockApi } from '../../test-utils'
import Projects from './Projects'

afterEach(() => vi.unstubAllGlobals())

const host = { project: 'AB', repo: '/r/ab', provider: 'github', path: 'me/app', source: 'override', detected: null }
const project = (over: Record<string, unknown> = {}) => ({
  key: 'AB',
  name: 'Alpha',
  repo_path: '/r/ab',
  repo_exists: true,
  jira: true,
  host,
  jira_connected: true,
  gitlab_connected: false,
  github_connected: true,
  test_apps_configured: false,
  status: [
    { id: 'repo', label: 'Local repo found', done: true },
    { id: 'host', label: 'Git host project set', done: true },
    { id: 'tests', label: 'Test apps set', done: false },
  ],
  cards: null,
  card_warnings: null,
  ...over,
})
const pcard = (key: string, over: Record<string, unknown> = {}) => ({
  key,
  summary: `Summary ${key}`,
  status: 'To Do',
  source: 'jira',
  url: 'u',
  eligible: true,
  plan_state: null,
  implementation_state: null,
  review_state: null,
  test_state: null,
  ...over,
})

function renderPage() {
  render(
    <MemoryRouter>
      <Projects />
    </MemoryRouter>,
  )
}

test('lists projects with chips and setup progress, and a checklist on expand', async () => {
  mockApi({ '/api/projects': { body: [project()] }, '/api/projects/AB': { body: project({ cards: [] }) } })
  renderPage()
  const summary = await screen.findByRole('button', { name: /Alpha/ })
  expect(within(summary).getByText('AB')).toBeInTheDocument()
  expect(within(summary).getByText('Jira')).toBeInTheDocument()
  expect(within(summary).getByText('GitHub')).toBeInTheDocument()
  expect(within(summary).getByText('2/3 set up')).toBeInTheDocument()
  await userEvent.click(summary)
  const list = await screen.findByRole('list', { name: 'Setup checklist' })
  expect(within(list).getByText('Test apps set')).toBeInTheDocument()
  expect(within(list).getByRole('link', { name: 'Set up' })).toHaveAttribute('href', '/settings/test-apps')
})

test('expanding shows the cards grouped, linked and with their step', async () => {
  mockApi({
    '/api/projects': { body: [project()] },
    '/api/projects/AB': {
      body: project({
        cards: [
          pcard('AB-1'),
          pcard('AB-2', { plan_state: 'approved' }),
          pcard('AB-3', { status: 'Done', eligible: false, plan_state: 'approved', implementation_state: 'completed', review_state: 'clean' }),
        ],
      }),
    },
  })
  renderPage()
  await userEvent.click(await screen.findByRole('button', { name: /Alpha/ }))
  const link = await screen.findByRole('link', { name: 'AB-1' })
  expect(link).toHaveAttribute('href', '/cards/AB-1')
  expect(within(screen.getByRole('list', { name: 'To Do' })).getByText('No plan')).toBeInTheDocument()
  expect(within(screen.getByRole('list', { name: 'In Progress' })).getByText('Plan approved')).toBeInTheDocument()
  expect(within(screen.getByRole('list', { name: 'In Review/Done' })).getByText('Reviewed')).toBeInTheDocument()
})

test('shows an empty state and a warning when a card source failed', async () => {
  mockApi({
    '/api/projects': { body: [project(), project({ key: 'CD', name: 'Beta' })] },
    '/api/projects/AB': { body: project({ cards: [] }) },
    '/api/projects/CD': { body: project({ key: 'CD', name: 'Beta', cards: [pcard('CD-1')], card_warnings: 'GitHub returned 500' }) },
  })
  renderPage()
  await userEvent.click(await screen.findByRole('button', { name: /Alpha/ }))
  expect(await screen.findByText('No cards')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: /Beta/ }))
  expect(await screen.findByRole('note', { name: '' })).toBeInTheDocument()
  expect(screen.getByText('GitHub returned 500')).toBeInTheDocument()
  expect(screen.queryByRole('alert')).toBeNull()
})

test('shows an empty list message', async () => {
  mockApi({ '/api/projects': { body: [] } })
  renderPage()
  expect(await screen.findByText(/No projects yet/)).toBeInTheDocument()
})

test('shows load errors in an error alert', async () => {
  mockApi({ '/api/projects': { status: 500, body: { detail: 'boom' } } })
  renderPage()
  expect(await screen.findByRole('alert')).toHaveTextContent('boom')
})

test('the form sends the Jira + GitLab payload', async () => {
  const fetchMock = mockApi({
    '/api/projects': [{ body: [] }, { body: [project()] }],
    'POST /api/projects': { status: 201, body: project({ cards: null }) },
    '/api/projects/AB': { body: project({ cards: [] }) },
  })
  renderPage()
  await userEvent.click(await screen.findByRole('button', { name: 'Add project' }))
  const dialog = screen.getByRole('dialog')
  expect(within(dialog).getByRole('button', { name: 'Create' })).toBeDisabled()
  await userEvent.type(within(dialog).getByLabelText('Project name'), 'Alpha')
  await userEvent.type(within(dialog).getByLabelText('Jira project key'), 'ab')
  await userEvent.type(within(dialog).getByLabelText('Repo path'), '/r/ab')
  await userEvent.type(within(dialog).getByLabelText('GitLab project path'), 'g/p')
  await userEvent.click(within(dialog).getByRole('button', { name: 'Create' }))
  await screen.findByRole('list', { name: 'Setup checklist' })
  const post = fetchMock.mock.calls.find(([, i]) => i?.method === 'POST')!
  expect(JSON.parse(String(post[1]?.body))).toEqual({
    name: 'Alpha',
    repo_path: '/r/ab',
    key: 'AB',
    jira_enabled: true,
    provider: 'gitlab',
    host_path: 'g/p',
    ai_provider: null,
  })
})

test('GitHub only hides the Jira key, requires the repo, and sends no key', async () => {
  const fetchMock = mockApi({
    '/api/projects': [{ body: [] }, { body: [project({ key: 'GH_APP', jira: false })] }],
    'POST /api/projects': { status: 201, body: project({ key: 'GH_APP', jira: false }) },
    '/api/projects/GH_APP': { body: project({ key: 'GH_APP', jira: false, cards: [] }) },
  })
  renderPage()
  await userEvent.click(await screen.findByRole('button', { name: 'Add project' }))
  const dialog = screen.getByRole('dialog')
  await userEvent.click(within(dialog).getByRole('combobox', { name: 'Type' }))
  await userEvent.click(screen.getByRole('option', { name: 'GitHub only' }))
  expect(within(dialog).queryByLabelText('Jira project key')).toBeNull()
  await userEvent.type(within(dialog).getByLabelText('Project name'), 'App')
  await userEvent.type(within(dialog).getByLabelText('Repo path'), '/r/app')
  expect(within(dialog).getByRole('button', { name: 'Create' })).toBeDisabled()
  await userEvent.type(within(dialog).getByLabelText('GitHub project path'), 'me/app')
  await userEvent.click(within(dialog).getByRole('button', { name: 'Create' }))
  await screen.findByRole('list', { name: 'Setup checklist' })
  const post = fetchMock.mock.calls.find(([, i]) => i?.method === 'POST')!
  expect(JSON.parse(String(post[1]?.body))).toEqual({
    name: 'App',
    repo_path: '/r/app',
    key: null,
    jira_enabled: false,
    provider: 'github',
    host_path: 'me/app',
    ai_provider: null,
  })
})

test('API errors from saving show as an error alert in the form', async () => {
  mockApi({
    '/api/projects': { body: [] },
    'POST /api/projects': { status: 409, body: { detail: 'A project with key AB already exists' } },
  })
  renderPage()
  await userEvent.click(await screen.findByRole('button', { name: 'Add project' }))
  const dialog = screen.getByRole('dialog')
  await userEvent.type(within(dialog).getByLabelText('Project name'), 'A')
  await userEvent.type(within(dialog).getByLabelText('Jira project key'), 'AB')
  await userEvent.type(within(dialog).getByLabelText('Repo path'), '/r')
  await userEvent.click(within(dialog).getByRole('button', { name: 'Create' }))
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('already exists')
})

test('editing sends a PUT without changing the key, and delete asks for confirmation', async () => {
  const fetchMock = mockApi({
    '/api/projects': [{ body: [project()] }, { body: [project({ name: 'Renamed' })] }, { body: [] }],
    '/api/projects/AB': { body: project({ cards: [] }) },
    'PUT /api/projects/AB': { body: project({ name: 'Renamed' }) },
    'DELETE /api/projects/AB': { status: 204, body: null },
  })
  renderPage()
  await userEvent.click(await screen.findByRole('button', { name: /Alpha/ }))
  await userEvent.click(await screen.findByRole('button', { name: 'Edit' }))
  const dialog = screen.getByRole('dialog')
  expect(within(dialog).getByLabelText('Jira project key')).toBeDisabled()
  const name = within(dialog).getByLabelText('Project name')
  await userEvent.clear(name)
  await userEvent.type(name, 'Renamed')
  await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
  const put = fetchMock.mock.calls.find(([, i]) => i?.method === 'PUT')!
  expect(JSON.parse(String(put[1]?.body))).toMatchObject({ name: 'Renamed', provider: 'github', host_path: 'me/app' })

  await userEvent.click(await screen.findByRole('button', { name: 'Delete' }))
  expect(fetchMock.mock.calls.some(([, i]) => i?.method === 'DELETE')).toBe(false)
  await userEvent.click(screen.getByRole('button', { name: 'Confirm delete' }))
  expect(await screen.findByText(/No projects yet/)).toBeInTheDocument()
  expect(fetchMock.mock.calls.some(([, i]) => i?.method === 'DELETE')).toBe(true)
})

test('Check host reports the default branch', async () => {
  mockApi({
    '/api/projects': { body: [project()] },
    '/api/projects/AB': { body: project({ cards: [] }) },
    '/api/repo-hosts/AB/check': { body: { provider: 'github', path: 'me/app', web_url: 'u', default_branch: 'main' } },
  })
  renderPage()
  await userEvent.click(await screen.findByRole('button', { name: /Alpha/ }))
  await userEvent.click(await screen.findByRole('button', { name: 'Check host' }))
  expect(await screen.findByRole('status')).toHaveTextContent('default branch main')
})

const aiProviders = [
  { id: 'copilot', label: 'GitHub Copilot CLI', configured: true, is_default: false },
  { id: 'anthropic', label: 'Anthropic', configured: false, is_default: false },
  { id: 'gemini', label: 'Google Gemini', configured: true, is_default: true },
]

test('the AI provider select shows the default, notes the agent limit and is sent on save', async () => {
  const fetchMock = mockApi({
    '/api/projects': [{ body: [] }, { body: [project()] }],
    '/api/ai/providers': { body: aiProviders },
    'POST /api/projects': { status: 201, body: project() },
  })
  renderPage()
  await userEvent.click(await screen.findByRole('button', { name: /Add project/ }))
  const dialog = screen.getByRole('dialog')
  const select = within(dialog).getByRole('combobox', { name: 'AI provider' })
  expect(await within(dialog).findByText('Default (Google Gemini)')).toBeInTheDocument()
  expect(within(dialog).getByText(/always use GitHub Copilot CLI for now/)).toBeInTheDocument()
  await userEvent.type(within(dialog).getByLabelText('Project name'), 'Alpha')
  await userEvent.type(within(dialog).getByLabelText('Jira project key'), 'ab')
  await userEvent.type(within(dialog).getByLabelText('Repo path'), '/r/ab')
  await userEvent.click(select)
  await userEvent.click(within(screen.getByRole('listbox')).getByText('Anthropic'))
  await userEvent.click(within(dialog).getByRole('button', { name: 'Create' }))
  const post = fetchMock.mock.calls.find(([, i]) => i?.method === 'POST')!
  expect(JSON.parse(String(post[1]?.body))).toMatchObject({ ai_provider: 'anthropic' })
})

test('the checklist shows the effective AI provider and links to the providers tab', async () => {
  const ai = { id: 'ai', label: 'AI provider: Anthropic (no API key)', done: false }
  const p = project({ ai_provider: 'anthropic', effective_ai_provider: 'anthropic' })
  p.status.push(ai)
  mockApi({ '/api/projects': { body: [p] }, '/api/projects/AB': { body: { ...p, cards: [] } } })
  renderPage()
  await userEvent.click(await screen.findByRole('button', { name: /Alpha/ }))
  expect(await screen.findByText('AI provider: Anthropic (no API key)')).toBeInTheDocument()
  const item = screen.getByText('AI provider: Anthropic (no API key)').closest('li')!
  expect(within(item).getByRole('link', { name: 'Set up' })).toHaveAttribute('href', '/settings/ai-providers')
})
