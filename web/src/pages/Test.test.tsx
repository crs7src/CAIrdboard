import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { mockApi, testRun } from '../test-utils'
import Test, { TEST_POLL_MS } from './Test'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const HEADER = /^Test (not started|starting the app|app running|stopped|failed)/
const NONE = { status: 404, body: { detail: 'No test run exists for this card' } }
const open = async () => userEvent.click(await screen.findByRole('button', { name: HEADER }))

test('is collapsed with a start button; starting shows progress', async () => {
  const fetchMock = mockApi({
    '/api/cards/AB-1/test': NONE,
    'POST /api/cards/AB-1/test': { status: 202, body: testRun({ state: 'preparing', links: [] }) },
  })
  render(<Test cardKey="AB-1" />)
  const header = await screen.findByRole('button', { name: HEADER })
  expect(header).toHaveAttribute('aria-expanded', 'false')
  await userEvent.click(screen.getByRole('button', { name: 'Start test' }))
  await open()
  expect(await screen.findByText(/Working out how to run the app/)).toBeInTheDocument()
  expect(fetchMock.mock.calls.some(([, i]) => i?.method === 'POST')).toBe(true)
})

test('polls while preparing, then shows links that open in a new tab', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  mockApi({
    '/api/cards/AB-1/test': [
      { body: testRun({ state: 'preparing', links: [] }) },
      { body: testRun({ report: 'Dark mode was added' }) },
    ],
  })
  render(<Test cardKey="AB-1" />)
  await open()
  await screen.findByText(/Working out how to run the app/)
  await vi.advanceTimersByTimeAsync(TEST_POLL_MS + 100)
  const link = await screen.findByRole('link', { name: 'Settings page' })
  expect(link).toHaveAttribute('href', 'http://localhost:5173/settings')
  expect(link).toHaveAttribute('target', '_blank')
  expect(screen.getByText('Toggle dark mode')).toBeInTheDocument()
  expect(screen.getByText('Dark mode was added')).toBeInTheDocument()
  expect(screen.getByRole('list', { name: 'Running apps' })).toHaveTextContent('web')
  expect(screen.getByRole('list', { name: 'Running apps' })).toHaveTextContent('npm run dev')
  expect(screen.queryByRole('button', { name: /Start test|Test again/ })).not.toBeInTheDocument()
})

test('Stop app stops it and allows testing again', async () => {
  const fetchMock = mockApi({
    '/api/cards/AB-1/test': { body: testRun() },
    'DELETE /api/cards/AB-1/test': { body: testRun({ state: 'stopped' }) },
  })
  render(<Test cardKey="AB-1" />)
  await open()
  await userEvent.click(await screen.findByRole('button', { name: 'Stop app' }))
  expect(await screen.findByRole('button', { name: 'Test again' })).toBeEnabled()
  expect(screen.queryByRole('link', { name: 'Settings page' })).not.toBeInTheDocument()
  expect(fetchMock.mock.calls.some(([, i]) => i?.method === 'DELETE')).toBe(true)
})

test('a failure shows the error and can be retried', async () => {
  mockApi({ '/api/cards/AB-1/test': { body: testRun({ state: 'failed', links: [], error: 'port in use' }) } })
  render(<Test cardKey="AB-1" />)
  await open()
  expect(await screen.findByText('port in use')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Test again' })).toBeEnabled()
})
