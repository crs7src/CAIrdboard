import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { mockApi } from '../../../test-utils'
import GitLabSettings from './GitLabSettings'

afterEach(() => vi.unstubAllGlobals())

const status = (over = {}) => ({ configured: true, connected: true, user: 'Me', url: 'https://git.x.com', ...over })
const info = (over = {}) => ({
  project: 'AB',
  repo: '/repo',
  provider: 'gitlab',
  path: 'grp/app',
  source: 'origin',
  detected: { provider: 'gitlab', path: 'grp/app' },
  ...over,
})

test('prefills the URL, never the token, and shows the connection', async () => {
  mockApi({ '/api/gitlab/status': { body: status() }, '/api/repo-hosts': { body: [] } })
  render(<GitLabSettings />)
  expect(await screen.findByLabelText('GitLab URL')).toHaveValue('https://git.x.com')
  expect(screen.getByLabelText('GitLab access token')).toHaveValue('')
  expect(await screen.findByText('Connected to GitLab as Me.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
})

test('sends only the changed field and reports the connected user', async () => {
  const fetchMock = mockApi({
    '/api/gitlab/status': [{ body: status() }, { body: status({ user: 'New' }) }],
    '/api/repo-hosts': { body: [] },
    'PUT /api/gitlab/credentials': { body: { connected: true, user: 'New' } },
  })
  render(<GitLabSettings />)
  await userEvent.type(await screen.findByLabelText('GitLab access token'), 'tok')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByText('Saved. Connected as New.')).toBeInTheDocument()
  const put = fetchMock.mock.calls.find(([, i]) => i?.method === 'PUT')!
  expect(JSON.parse(String(put[1]?.body))).toEqual({ token: 'tok' })
  expect(screen.getByLabelText('GitLab access token')).toHaveValue('')
})

test('shows a rejected credential error', async () => {
  mockApi({
    '/api/gitlab/status': { body: status({ configured: false, connected: false, user: null, url: '' }) },
    '/api/repo-hosts': { body: [] },
    'PUT /api/gitlab/credentials': { status: 400, body: { detail: 'GitLab did not accept these credentials' } },
  })
  render(<GitLabSettings />)
  await userEvent.type(await screen.findByLabelText('GitLab URL'), 'https://g.com')
  await userEvent.type(screen.getByLabelText('GitLab access token'), 'bad')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByText(/did not accept/)).toBeInTheDocument()
})

test('shows the detected project, overrides it, resets it and checks it', async () => {
  const fetchMock = mockApi({
    '/api/gitlab/status': { body: status() },
    '/api/repo-hosts': { body: [info()] },
    'PUT /api/repo-hosts/AB': { body: info({ source: 'override', path: 'o/p' }) },
    'DELETE /api/repo-hosts/AB': { body: info() },
    '/api/repo-hosts/AB/check': {
      body: { provider: 'gitlab', path: 'grp/app', web_url: 'u', default_branch: 'main' },
    },
  })
  render(<GitLabSettings />)
  const row = within(await screen.findByRole('group', { name: 'GitLab project AB' }))
  expect(row.getByText('Using grp/app (from origin remote)')).toBeInTheDocument()
  expect(row.getByRole('button', { name: 'Reset' })).toBeDisabled()

  await userEvent.click(row.getByRole('button', { name: 'Check' }))
  expect(await row.findByText('OK: grp/app, default branch main')).toBeInTheDocument()

  await userEvent.type(row.getByLabelText('GitLab project path'), 'o/p')
  await userEvent.click(row.getByRole('button', { name: 'Set' }))
  expect(await row.findByText('Using o/p (override)')).toBeInTheDocument()
  const put = fetchMock.mock.calls.find(([, i]) => i?.method === 'PUT' && String(i.body).includes('path'))!
  expect(JSON.parse(String(put[1]?.body))).toEqual({ provider: 'gitlab', path: 'o/p' })

  await userEvent.click(row.getByRole('button', { name: 'Reset' }))
  expect(await row.findByText('Using grp/app (from origin remote)')).toBeInTheDocument()
  expect(row.getByLabelText('GitLab project path')).toHaveValue('')
})

test('without a detected project the check is disabled and shows errors', async () => {
  mockApi({
    '/api/gitlab/status': { body: status() },
    '/api/repo-hosts': { body: [info({ detected: null, provider: null, path: null, source: null })] },
    'PUT /api/repo-hosts/AB': { status: 422, body: { detail: 'Use the project path' } },
  })
  render(<GitLabSettings />)
  const row = within(await screen.findByRole('group', { name: 'GitLab project AB' }))
  expect(row.getByText(/No GitLab project detected/)).toBeInTheDocument()
  expect(row.getByRole('button', { name: 'Check' })).toBeDisabled()
  await userEvent.type(row.getByLabelText('GitLab project path'), 'bad')
  await userEvent.click(row.getByRole('button', { name: 'Set' }))
  expect(await row.findByText('Use the project path')).toBeInTheDocument()
})
