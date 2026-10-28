import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { mockApi } from '../../test-utils'
import TestAppsSettings from './TestAppsSettings'

afterEach(() => vi.unstubAllGlobals())

const AI = { eligible_statuses: [], project_repos: { AB: '/repo' } }
const app = { name: 'api', start_command: 'run api', workdir: '.', ready_url: 'http://localhost:6000', ready_timeout_seconds: null }
const CONFIG = { project: 'AB', apps: [app], saved_from: 'settings', saved_at: 'now' }

test('lists configured projects and edits, adds and saves apps', async () => {
  const fetchMock = mockApi({
    '/api/ai-config': { body: AI },
    '/api/test-configs/AB': { body: CONFIG },
    'PUT /api/test-configs/AB': { body: CONFIG },
  })
  render(<TestAppsSettings />)
  await userEvent.click(await screen.findByRole('button', { name: /^AB/ }))
  expect(await screen.findByDisplayValue('run api')).toBeInTheDocument()
  expect(screen.getByText('Configured')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Add app' }))
  expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  const names = screen.getAllByLabelText('Name')
  await userEvent.type(names[1], 'web')
  await userEvent.type(screen.getAllByLabelText('Start command')[1], 'npm run dev')
  await userEvent.type(screen.getAllByLabelText('Ready URL')[1], 'http://localhost:6001')
  await userEvent.click(screen.getByRole('button', { name: 'Move web up' }))
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByText('Saved.')).toBeInTheDocument()
  const put = fetchMock.mock.calls.find(([, i]) => i?.method === 'PUT')!
  const sent = JSON.parse(String(put[1]?.body)).apps
  expect(sent.map((a: { name: string }) => a.name)).toEqual(['web', 'api'])
  expect(sent[0]).toMatchObject({ start_command: 'npm run dev', workdir: '.', ready_url: 'http://localhost:6001' })
})

test('clearing removes the settings, and save errors are shown', async () => {
  mockApi({
    '/api/ai-config': { body: AI },
    '/api/test-configs/AB': { body: CONFIG },
    'DELETE /api/test-configs/AB': { status: 204, body: null },
  })
  render(<TestAppsSettings />)
  await userEvent.click(await screen.findByRole('button', { name: /^AB/ }))
  await userEvent.click(await screen.findByRole('button', { name: 'Clear' }))
  expect(await screen.findByText('Not set')).toBeInTheDocument()
  expect(screen.queryByDisplayValue('run api')).not.toBeInTheDocument()
})

test('shows the server error when saving fails', async () => {
  mockApi({
    '/api/ai-config': { body: AI },
    '/api/test-configs/AB': { body: CONFIG },
    'PUT /api/test-configs/AB': { status: 422, body: { detail: 'bad workdir' } },
  })
  render(<TestAppsSettings />)
  await userEvent.click(await screen.findByRole('button', { name: /^AB/ }))
  await userEvent.type(await screen.findByLabelText('Start command'), ' x')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('bad workdir')
})
