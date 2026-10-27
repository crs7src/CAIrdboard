import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { mockApi, review } from '../test-utils'
import Review, { REVIEW_POLL_MS } from './Review'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const HEADER = /^Review (not started|running|clean|fixes made|failed)/
const NONE = { status: 404, body: { detail: 'No review exists for this card' } }
const open = async () => userEvent.click(await screen.findByRole('button', { name: HEADER }))

test('is collapsed with a start button; starting shows progress', async () => {
  const fetchMock = mockApi({
    '/api/cards/AB-1/review': NONE,
    'POST /api/cards/AB-1/review': { status: 202, body: review({ state: 'running' }) },
  })
  render(<Review cardKey="AB-1" />)
  const header = await screen.findByRole('button', { name: HEADER })
  expect(header).toHaveAttribute('aria-expanded', 'false')
  expect(screen.getByText('not started')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Start review' }))
  await open()
  expect(await screen.findByText('Reviewing the changes...')).toBeInTheDocument()
  expect(fetchMock.mock.calls.some(([, i]) => i?.method === 'POST')).toBe(true)
})

test('polls while running and shows the report when clean, with no more play button', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  mockApi({
    '/api/cards/AB-1/review': [
      { body: review({ state: 'running' }) },
      { body: review({ state: 'clean', report: '## Review summary\n\nAll good' }) },
    ],
  })
  render(<Review cardKey="AB-1" />)
  await open()
  await screen.findByText('Reviewing the changes...')
  await vi.advanceTimersByTimeAsync(REVIEW_POLL_MS + 100)
  expect(await screen.findByRole('heading', { name: 'Review summary' })).toBeInTheDocument()
  expect(screen.getByText('clean')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Start review|Review again/ })).not.toBeInTheDocument()
})

test('fixes need another review and can be rerun', async () => {
  mockApi({
    '/api/cards/AB-1/review': {
      body: review({ state: 'fixed', fix_commits: [{ sha: 'abc1234', subject: 'AB-1: review fix - null check' }] }),
    },
    'POST /api/cards/AB-1/review': { status: 202, body: review({ version: 2, state: 'running' }) },
  })
  render(<Review cardKey="AB-1" />)
  await open()
  expect(await screen.findByText('AB-1: review fix - null check')).toBeInTheDocument()
  expect(screen.getByText(/needs another review/)).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Review again' }))
  expect(await screen.findByText('Reviewing the changes...')).toBeInTheDocument()
})

test('shows a failure and refused starts', async () => {
  mockApi({
    '/api/cards/AB-1/review': { body: review({ state: 'failed', error: 'boom' }) },
    'POST /api/cards/AB-1/review': { status: 409, body: { detail: 'Already being worked on' } },
  })
  render(<Review cardKey="AB-1" />)
  await open()
  expect(await screen.findByText('boom')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Review again' }))
  expect(await screen.findByText('Already being worked on')).toBeInTheDocument()
})
