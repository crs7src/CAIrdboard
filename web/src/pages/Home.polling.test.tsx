import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { card, mockApi } from '../test-utils'
import Home from './Home'

beforeEach(() => vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] }))
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const config = { eligible_statuses: ['To Do'], project_repos: { AB: '/r' } }
const base = {
  '/api/cards': { body: [card('AB-1')] },
  '/api/ai-config': { body: config },
  '/api/test-configs': { body: ['AB'] },
}

function renderHome() {
  render(
    <MemoryRouter>
      <Home />
    </MemoryRouter>,
  )
}

const tick = () => act(() => vi.advanceTimersByTimeAsync(3000))

test('a running implementation turns into a check after the poll returns completed', async () => {
  mockApi({
    ...base,
    '/api/plans': { body: { 'AB-1': 'approved' } },
    '/api/implementations': [{ body: { 'AB-1': 'running' } }, { body: { 'AB-1': 'completed' } }],
  })
  renderHome()
  const button = await screen.findByRole('button', { name: 'Implement' })
  expect(button).toBeDisabled()
  expect(screen.getByRole('progressbar')).toBeInTheDocument()
  await tick()
  expect(await screen.findByRole('img', { name: 'Implement' })).toBeInTheDocument()
  expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
})

const failing = [
  ['Plan', { '/api/plans': [{ body: { 'AB-1': 'running' } }, { body: { 'AB-1': 'failed' } }] }],
  [
    'Implement',
    {
      '/api/plans': { body: { 'AB-1': 'approved' } },
      '/api/implementations': [{ body: { 'AB-1': 'running' } }, { body: { 'AB-1': 'failed' } }],
    },
  ],
  [
    'Review',
    {
      '/api/plans': { body: { 'AB-1': 'approved' } },
      '/api/implementations': { body: { 'AB-1': 'completed' } },
      '/api/reviews': [{ body: { 'AB-1': 'running' } }, { body: { 'AB-1': 'failed' } }],
    },
  ],
  [
    'Test',
    {
      '/api/plans': { body: { 'AB-1': 'approved' } },
      '/api/implementations': { body: { 'AB-1': 'completed' } },
      '/api/reviews': { body: { 'AB-1': 'clean' } },
      '/api/tests': [{ body: { 'AB-1': 'preparing' } }, { body: { 'AB-1': 'failed' } }],
    },
  ],
  [
    'Create MR',
    {
      '/api/plans': { body: { 'AB-1': 'approved' } },
      '/api/implementations': { body: { 'AB-1': 'completed' } },
      '/api/reviews': { body: { 'AB-1': 'clean' } },
      '/api/test-approvals': { body: ['AB-1'] },
      '/api/merge-requests': [{ body: { 'AB-1': 'running' } }, { body: { 'AB-1': 'failed' } }],
    },
  ],
] as const

test.each(failing)('a running %s step turns into a failed icon after the poll', async (label, routes) => {
  mockApi({ ...base, ...routes } as Parameters<typeof mockApi>[0])
  renderHome()
  await vi.waitFor(() => expect(screen.getByRole('progressbar')).toBeInTheDocument())
  await tick()
  const retry = await screen.findByRole('button', { name: `${label} failed` })
  expect(retry).toBeEnabled()
  expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
})

test('polling stops once nothing is active', async () => {
  const fetchMock = mockApi({
    ...base,
    '/api/plans': { body: { 'AB-1': 'approved' } },
    '/api/implementations': [{ body: { 'AB-1': 'running' } }, { body: { 'AB-1': 'completed' } }],
  })
  renderHome()
  await screen.findByRole('progressbar')
  await tick()
  await screen.findByRole('img', { name: 'Implement' })
  const calls = () => fetchMock.mock.calls.filter(([u]) => u === '/api/implementations').length
  const before = calls()
  await tick()
  await tick()
  expect(calls()).toBe(before)
  // Polling only reloads step states, never the Jira cards.
  expect(fetchMock.mock.calls.filter(([u]) => u === '/api/cards')).toHaveLength(1)
})

test('a failed start shows the error and no spinner', async () => {
  mockApi({
    ...base,
    '/api/plans': { body: {} },
    '/api/implementations': { body: {} },
    'POST /api/cards/AB-1/plan': { status: 409, body: { detail: 'Busy repo' } },
  })
  renderHome()
  await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).click(await screen.findByRole('button', { name: 'Plan' }))
  expect(await screen.findByText('Busy repo')).toBeInTheDocument()
  expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
})
