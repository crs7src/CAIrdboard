import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { implementation, mockApi } from '../../test-utils'
import Implementation, { IMPL_POLL_MS } from './Implementation'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

async function openImpl() {
  await userEvent.click(await screen.findByRole('button', { name: /^Implementation/ }))
}

const NONE = { status: 404, body: { detail: 'No implementation exists for this card' } }

test('offers to start when nothing has run yet, then shows progress', async () => {
  const fetchMock = mockApi({
    '/api/cards/AB-1/implementation': NONE,
    'POST /api/cards/AB-1/implementation': {
      status: 202,
      body: implementation({ state: 'running', stage: 'preparing', branch: null }),
    },
  })
  render(<Implementation cardKey="AB-1" />)
  await userEvent.click(await screen.findByRole('button', { name: 'Start implementation' }))
  await openImpl()
  expect(await screen.findByText('Preparing branch...')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Start implementation' })).not.toBeInTheDocument()
  expect(fetchMock.mock.calls.some(([, i]) => i?.method === 'POST')).toBe(true)
})

test('polls while running and shows branch, live commits and the final report', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  mockApi({
    '/api/cards/AB-1/implementation': [
      {
        body: implementation({
          state: 'running',
          stage: 'implementing',
          commits: [{ sha: 'aaa111', subject: 'AB-1: step 1 - add toggle' }],
        }),
      },
      {
        body: implementation({
          commits: [
            { sha: 'aaa111', subject: 'AB-1: step 1 - add toggle' },
            { sha: 'bbb222', subject: 'AB-1: step 2 - add tests' },
          ],
          report: '## Review against the plan\n\nAll steps matched',
        }),
      },
    ],
  })
  render(<Implementation cardKey="AB-1" />)
  await openImpl()
  expect(await screen.findByText('Implementing...')).toBeInTheDocument()
  expect(screen.getByText('AB-1_add_dark_mode')).toBeInTheDocument()
  expect(screen.getByText('AB-1: step 1 - add toggle')).toBeInTheDocument()

  await vi.advanceTimersByTimeAsync(IMPL_POLL_MS + 100)
  expect(await screen.findByText('AB-1: step 2 - add tests')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Review against the plan' })).toBeInTheDocument()
  expect(screen.getByText('completed')).toBeInTheDocument()
  expect(screen.queryByText('Implementing...')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /implementation/ })).not.toBeInTheDocument()
})

test('a failed run shows the error and can be retried', async () => {
  mockApi({
    '/api/cards/AB-1/implementation': {
      body: implementation({ state: 'failed', error: 'The repo has uncommitted changes.', notes: ['Heads up'] }),
    },
    'POST /api/cards/AB-1/implementation': { status: 202, body: implementation({ state: 'running', stage: 'preparing' }) },
  })
  render(<Implementation cardKey="AB-1" />)
  await openImpl()
  expect(await screen.findByText('The repo has uncommitted changes.')).toBeInTheDocument()
  expect(screen.getByText('Heads up')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Retry implementation' }))
  expect(await screen.findByText('Preparing branch...')).toBeInTheDocument()
})

test('shows the server error when starting is refused', async () => {
  mockApi({
    '/api/cards/AB-1/implementation': NONE,
    'POST /api/cards/AB-1/implementation': {
      status: 409,
      body: { detail: 'Another implementation is running in this repo.' },
    },
  })
  render(<Implementation cardKey="AB-1" />)
  await userEvent.click(await screen.findByRole('button', { name: 'Start implementation' }))
  await openImpl()
  expect(await screen.findByRole('alert')).toHaveTextContent('Another implementation is running')
})

test('is collapsed by default and shows the status in the header', async () => {
  mockApi({ '/api/cards/AB-1/implementation': NONE })
  render(<Implementation cardKey="AB-1" />)
  const header = await screen.findByRole('button', { name: /^Implementation/ })
  expect(header).toHaveAttribute('aria-expanded', 'false')
  expect(screen.getByText('not started')).toBeInTheDocument()
})
