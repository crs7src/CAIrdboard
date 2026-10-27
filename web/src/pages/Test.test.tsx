import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { mockApi, testRun } from '../test-utils'

const CONFIG = {
  project: 'AB',
  apps: testRun().apps,
  saved_from: 'AB-1',
  saved_at: 't',
}
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
    '/api/cards/AB-1/test/config': { body: CONFIG },
    'POST /api/cards/AB-1/test': { status: 202, body: testRun({ state: 'preparing', links: [] }) },
  })
  render(<Test cardKey="AB-1" />)
  await screen.findByText('saved settings')
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
    '/api/cards/AB-1/test/config': { body: CONFIG },
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
  mockApi({
    '/api/cards/AB-1/test': { body: testRun({ state: 'failed', links: [], error: 'port in use' }) },
    '/api/cards/AB-1/test/config': { body: CONFIG },
  })
  render(<Test cardKey="AB-1" />)
  await screen.findByText('saved settings')
  await open()
  expect(await screen.findByText('port in use')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Test again' })).toBeEnabled()
})

test('shows saved settings, and Start with AI asks the AI', async () => {
  const fetchMock = mockApi({
    '/api/cards/AB-1/test': { body: testRun({ state: 'stopped' }) },
    '/api/cards/AB-1/test/config': { body: CONFIG },
    'POST /api/cards/AB-1/test': { status: 202, body: testRun({ state: 'preparing', links: [] }) },
  })
  render(<Test cardKey="AB-1" />)
  expect(await screen.findByText('saved settings')).toBeInTheDocument()
  await open()
  await userEvent.click(await screen.findByRole('button', { name: 'Start with AI' }))
  const post = fetchMock.mock.calls.find(([, i]) => i?.method === 'POST')!
  expect(JSON.parse(String(post[1]?.body))).toEqual({ use_ai: true })
})

test('Forget saved settings removes them', async () => {
  const fetchMock = mockApi({
    '/api/cards/AB-1/test': { body: testRun({ state: 'stopped' }) },
    '/api/cards/AB-1/test/config': { body: CONFIG },
    'DELETE /api/cards/AB-1/test/config': { status: 204, body: null },
  })
  render(<Test cardKey="AB-1" />)
  await open()
  await userEvent.click(await screen.findByRole('button', { name: 'Forget saved settings' }))
  await vi.waitFor(() => expect(screen.queryByText('saved settings')).not.toBeInTheDocument())
  expect(fetchMock.mock.calls.some(([, i]) => i?.method === 'DELETE')).toBe(true)
})

test('reporting a problem sends the message and shows the restart', async () => {
  const fetchMock = mockApi({
    '/api/cards/AB-1/test': { body: testRun() },
    'POST /api/cards/AB-1/test/problem': {
      status: 202,
      body: testRun({ state: 'preparing', source: 'feedback', problem: 'login is blank', links: [] }),
    },
  })
  render(<Test cardKey="AB-1" />)
  await open()
  const send = await screen.findByRole('button', { name: 'Send problem report' })
  expect(send).toBeDisabled()
  await userEvent.type(screen.getByLabelText('Describe what is not running right'), 'login is blank')
  await userEvent.click(send)
  expect(await screen.findByText(/Fixing how the app starts/)).toBeInTheDocument()
  expect(screen.getByText(/Reported problem: login is blank/)).toBeInTheDocument()
  const post = fetchMock.mock.calls.find(([, i]) => i?.method === 'POST')!
  expect(JSON.parse(String(post[1]?.body))).toEqual({ message: 'login is blank' })
})

test('a run from saved settings just says it is starting the app', async () => {
  mockApi({
    '/api/cards/AB-1/test': { body: testRun({ state: 'preparing', source: 'saved', links: [] }) },
  })
  render(<Test cardKey="AB-1" />)
  await open()
  expect(await screen.findByText('Starting app...')).toBeInTheDocument()
  expect(screen.queryByText(/Working out how to run the app/)).not.toBeInTheDocument()
})

test('Start test is disabled until start settings exist, but Start with AI works', async () => {
  mockApi({ '/api/cards/AB-1/test': NONE })
  render(<Test cardKey="AB-1" />)
  await open()
  expect(await screen.findByRole('button', { name: 'Start test' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Start with AI' })).toBeEnabled()
})
