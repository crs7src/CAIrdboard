import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { mockApi } from '../test-utils'
import GitHubSettings from './GitHubSettings'

afterEach(() => vi.unstubAllGlobals())

const status = (over = {}) => ({ configured: true, connected: true, user: 'Me', url: 'https://api.github.com', ...over })
const info = (over = {}) => ({
  project: 'AB',
  repo: '/repo',
  provider: 'github',
  path: 'grp/app',
  source: 'origin',
  detected: { provider: 'github', path: 'grp/app' },
  ...over,
})

test('prefills the URL, never the token, and shows the connection', async () => {
  mockApi({ '/api/github/status': { body: status() }, '/api/repo-hosts': { body: [] } })
  render(<GitHubSettings />)
  expect(await screen.findByLabelText('GitHub URL')).toHaveValue('https://api.github.com')
  expect(screen.getByLabelText('GitHub access token')).toHaveValue('')
  expect(await screen.findByText('Connected to GitHub as Me.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
})

test('sends only the changed field and reports the connected user', async () => {
  const fetchMock = mockApi({
    '/api/github/status': [{ body: status() }, { body: status({ user: 'New' }) }],
    '/api/repo-hosts': { body: [] },
    'PUT /api/github/credentials': { body: { connected: true, user: 'New' } },
  })
  render(<GitHubSettings />)
  await userEvent.type(await screen.findByLabelText('GitHub access token'), 'tok')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByText('Saved. Connected as New.')).toBeInTheDocument()
  const put = fetchMock.mock.calls.find(([, i]) => i?.method === 'PUT')!
  expect(JSON.parse(String(put[1]?.body))).toEqual({ token: 'tok' })
  expect(screen.getByLabelText('GitHub access token')).toHaveValue('')
})

test('shows a rejected credential error', async () => {
  mockApi({
    '/api/github/status': { body: status({ configured: false, connected: false, user: null, url: '' }) },
    '/api/repo-hosts': { body: [] },
    'PUT /api/github/credentials': { status: 400, body: { detail: 'GitHub did not accept these credentials' } },
  })
  render(<GitHubSettings />)
  await userEvent.type(await screen.findByLabelText('GitHub URL'), 'https://g.com')
  await userEvent.type(screen.getByLabelText('GitHub access token'), 'bad')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByText(/did not accept/)).toBeInTheDocument()
})

test('shows the detected project, overrides it, resets it and checks it', async () => {
  const fetchMock = mockApi({
    '/api/github/status': { body: status() },
    '/api/repo-hosts': { body: [info()] },
    'PUT /api/repo-hosts/AB': { body: info({ source: 'override', path: 'o/p' }) },
    'DELETE /api/repo-hosts/AB': { body: info() },
    '/api/repo-hosts/AB/check': {
      body: { provider: 'github', path: 'grp/app', web_url: 'u', default_branch: 'main' },
    },
  })
  render(<GitHubSettings />)
  const row = within(await screen.findByRole('group', { name: 'GitHub project AB' }))
  expect(row.getByText('Using grp/app (from origin remote)')).toBeInTheDocument()
  expect(row.getByRole('button', { name: 'Reset' })).toBeDisabled()

  await userEvent.click(row.getByRole('button', { name: 'Check' }))
  expect(await row.findByText('OK: grp/app, default branch main')).toBeInTheDocument()

  await userEvent.type(row.getByLabelText('GitHub project path'), 'o/p')
  await userEvent.click(row.getByRole('button', { name: 'Set' }))
  expect(await row.findByText('Using o/p (override)')).toBeInTheDocument()
  const put = fetchMock.mock.calls.find(([, i]) => i?.method === 'PUT' && String(i.body).includes('path'))!
  expect(JSON.parse(String(put[1]?.body))).toEqual({ provider: 'github', path: 'o/p' })

  await userEvent.click(row.getByRole('button', { name: 'Reset' }))
  expect(await row.findByText('Using grp/app (from origin remote)')).toBeInTheDocument()
  expect(row.getByLabelText('GitHub project path')).toHaveValue('')
})

test('without a detected project the check is disabled and shows errors', async () => {
  mockApi({
    '/api/github/status': { body: status() },
    '/api/repo-hosts': { body: [info({ detected: null, provider: null, path: null, source: null })] },
    'PUT /api/repo-hosts/AB': { status: 422, body: { detail: 'Use the project path' } },
  })
  render(<GitHubSettings />)
  const row = within(await screen.findByRole('group', { name: 'GitHub project AB' }))
  expect(row.getByText(/No GitHub project detected/)).toBeInTheDocument()
  expect(row.getByRole('button', { name: 'Check' })).toBeDisabled()
  await userEvent.type(row.getByLabelText('GitHub project path'), 'bad')
  await userEvent.click(row.getByRole('button', { name: 'Set' }))
  expect(await row.findByText('Use the project path')).toBeInTheDocument()
})

test('a project mapped to the other provider can be switched to this one', async () => {
  const fetchMock = mockApi({
    '/api/github/status': { body: status() },
    '/api/repo-hosts': { body: [info({ provider: 'gitlab', path: 'g/s/p', detected: null, source: 'origin' })] },
    'PUT /api/repo-hosts/AB': { body: info({ source: 'override', path: 'me/app' }) },
  })
  render(<GitHubSettings />)
  const row = within(await screen.findByRole('group', { name: 'GitHub project AB' }))
  expect(row.getByText('Using GitLab project g/s/p (from origin remote)')).toBeInTheDocument()
  await userEvent.type(row.getByLabelText('GitHub project path'), 'me/app')
  await userEvent.click(row.getByRole('button', { name: 'Set' }))
  expect(await row.findByText('Using me/app (override)')).toBeInTheDocument()
  const put = fetchMock.mock.calls.find(([, i]) => i?.method === 'PUT')!
  expect(JSON.parse(String(put[1]?.body))).toEqual({ provider: 'github', path: 'me/app' })
})
