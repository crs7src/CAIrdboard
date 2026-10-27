import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { card, mockApi } from '../test-utils'
import Home from './Home'

afterEach(() => vi.unstubAllGlobals())

const config = {
  eligible_statuses: ['To Do', 'Backlog'],
  project_repos: {},
}

function LocationProbe() {
  const { pathname, search } = useLocation()
  return <p>{pathname + search}</p>
}

function renderHome() {
  render(
    <MemoryRouter>
      <Home />
    </MemoryRouter>,
  )
}

test('lists cards with links to their detail page', async () => {
  mockApi({
    '/api/cards': { body: [card('AB-1'), card('AB-2', { priority: null })] },
    '/api/plans': { body: {} },
    '/api/ai-config': { body: config },
  })
  renderHome()
  expect(await screen.findByRole('link', { name: /AB-1/ })).toHaveAttribute('href', '/cards/AB-1')
  expect(screen.getByText('Summary AB-2')).toBeInTheDocument()
  expect(screen.getAllByText('High')).toHaveLength(1)
})

test('eligible cards without a plan show a Plan: available chip; others do not', async () => {
  mockApi({
    '/api/cards': {
      body: [card('AB-1'), card('AB-2', { status: 'Testing' }), card('AB-3', { status: 'ready to play' })],
    },
    '/api/plans': { body: {} },
    '/api/ai-config': { body: { ...config, eligible_statuses: ['To Do', 'Ready to Play'] } },
  })
  renderHome()
  await screen.findByRole('link', { name: /AB-1/ })
  const available = screen.getAllByText('Plan: available')
  expect(available.map((c) => c.closest('a')?.getAttribute('href'))).toEqual(['/cards/AB-1', '/cards/AB-3'])
})

test('the whole card is a single link to its detail page', async () => {
  mockApi({ '/api/cards': { body: [card('AB-1')] }, '/api/plans': { body: {} }, '/api/ai-config': { body: config } })
  renderHome()
  const link = await screen.findByRole('link', { name: /AB-1/ })
  expect(link).toHaveTextContent('Summary AB-1')
  expect(screen.getAllByRole('link')).toHaveLength(1)
})

test('shows the plan state chip for cards that have a plan', async () => {
  mockApi({
    '/api/cards': { body: [card('AB-1')] },
    '/api/plans': { body: { 'AB-1': 'approved' } },
    '/api/ai-config': { body: config },
  })
  renderHome()
  expect(await screen.findByText('Implementation: available')).toBeInTheDocument()
  expect(screen.queryByText('Plan: approved')).not.toBeInTheDocument()
  expect(screen.queryByText('Plan: available')).not.toBeInTheDocument()
})

test('shows the implementation state once one exists', async () => {
  mockApi({
    '/api/cards': { body: [card('AB-1')] },
    '/api/plans': { body: { 'AB-1': 'approved' } },
    '/api/implementations': { body: { 'AB-1': 'running' } },
    '/api/ai-config': { body: config },
  })
  renderHome()
  expect(await screen.findByText('Implementation: running')).toBeInTheDocument()
})

test('shows the plan chip while the plan is not approved', async () => {
  mockApi({
    '/api/cards': { body: [card('AB-1')] },
    '/api/plans': { body: { 'AB-1': 'ready' } },
    '/api/implementations': { body: {} },
    '/api/ai-config': { body: config },
  })
  renderHome()
  expect(await screen.findByText('Plan: ready')).toBeInTheDocument()
})

test('still lists cards if plan info fails to load', async () => {
  mockApi({ '/api/cards': { body: [card('AB-1')] } })
  renderHome()
  expect(await screen.findByRole('link', { name: /AB-1/ })).toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('shows an empty state', async () => {
  mockApi({ '/api/cards': { body: [] } })
  renderHome()
  expect(await screen.findByText('No cards assigned to you.')).toBeInTheDocument()
})

test('shows the server error detail with a link to settings', async () => {
  mockApi({
    '/api/cards': { status: 503, body: { detail: 'Jira is not configured' } },
  })
  renderHome()
  expect(await screen.findByRole('alert')).toHaveTextContent('Jira is not configured')
  expect(screen.getByRole('link', { name: 'Update your Jira settings' })).toHaveAttribute(
    'href',
    '/settings/jira',
  )
})

test('Sync button refetches cards', async () => {
  const fetchMock = mockApi({
    '/api/cards': [{ body: [card('AB-1')] }, { body: [card('AB-1'), card('AB-3')] }],
  })
  renderHome()
  await screen.findByRole('link', { name: /AB-1/ })
  await userEvent.click(screen.getByRole('button', { name: 'Sync' }))
  expect(await screen.findByRole('link', { name: /AB-3/ })).toBeInTheDocument()
  expect(fetchMock.mock.calls.filter(([u]) => u === '/api/cards')).toHaveLength(2)
})

const withRepo = { ...config, project_repos: { AB: '/r' } }
const enabled = (name: string) => screen.getByRole('button', { name })

test('only the next step button is enabled and review is always disabled', async () => {
  mockApi({
    '/api/cards': { body: [card('AB-1')] },
    '/api/plans': { body: {} },
    '/api/implementations': { body: {} },
    '/api/ai-config': { body: withRepo },
  })
  renderHome()
  await screen.findByRole('link', { name: /AB-1/ })
  expect(enabled('Plan')).toBeEnabled()
  expect(enabled('Implement')).toBeDisabled()
  expect(enabled('Review')).toBeDisabled()
})

test('a completed plan shows a green check and unlocks implement', async () => {
  mockApi({
    '/api/cards': { body: [card('AB-1')] },
    '/api/plans': { body: { 'AB-1': 'approved' } },
    '/api/implementations': { body: {} },
    '/api/ai-config': { body: withRepo },
  })
  renderHome()
  expect(await screen.findByRole('img', { name: 'Plan' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Plan' })).not.toBeInTheDocument()
  expect(enabled('Implement')).toBeEnabled()
})

test('a completed implementation shows a check and unlocks review', async () => {
  mockApi({
    '/api/cards': { body: [card('AB-1')] },
    '/api/plans': { body: { 'AB-1': 'approved' } },
    '/api/implementations': { body: { 'AB-1': 'completed' } },
    '/api/reviews': { body: {} },
    '/api/ai-config': { body: withRepo },
  })
  renderHome()
  expect(await screen.findByRole('img', { name: 'Implement' })).toBeInTheDocument()
  expect(enabled('Review')).toBeEnabled()
  expect(screen.getByText('Review: available')).toBeInTheDocument()
})

test('a clean review shows a check; a review with fixes can be run again', async () => {
  mockApi({
    '/api/cards': { body: [card('AB-1'), card('AB-2')] },
    '/api/plans': { body: { 'AB-1': 'approved', 'AB-2': 'approved' } },
    '/api/implementations': { body: { 'AB-1': 'completed', 'AB-2': 'completed' } },
    '/api/reviews': { body: { 'AB-1': 'clean', 'AB-2': 'fixed' } },
    '/api/ai-config': { body: withRepo },
  })
  renderHome()
  expect(await screen.findByText('Test: available')).toBeInTheDocument()
  expect(screen.getByText('Review: fixed')).toBeInTheDocument()
  expect(screen.getAllByRole('img', { name: 'Review' })).toHaveLength(1)
  expect(screen.getAllByRole('button', { name: 'Review' })).toHaveLength(1)
})

test('clicking Review starts the review', async () => {
  const fetchMock = mockApi({
    '/api/cards': { body: [card('AB-1')] },
    '/api/plans': { body: { 'AB-1': 'approved' } },
    '/api/implementations': { body: { 'AB-1': 'completed' } },
    '/api/reviews': { body: {} },
    '/api/ai-config': { body: withRepo },
    'POST /api/cards/AB-1/review': { status: 202, body: { state: 'running' } },
  })
  renderHome()
  await userEvent.click(await screen.findByRole('button', { name: 'Review' }))
  await vi.waitFor(() => expect(screen.getByText('Review: running')).toBeInTheDocument())
  expect(fetchMock.mock.calls.some(([, i]) => i?.method === 'POST')).toBe(true)
})

test('clicking Plan starts the plan without opening the card', async () => {
  const fetchMock = mockApi({
    '/api/cards': { body: [card('AB-1')] },
    '/api/plans': { body: {} },
    '/api/implementations': { body: {} },
    '/api/ai-config': { body: withRepo },
    'POST /api/cards/AB-1/plan': { status: 202, body: { state: 'running' } },
  })
  renderHome()
  await userEvent.click(await screen.findByRole('button', { name: 'Plan' }))
  await vi.waitFor(() => expect(screen.getByText('Plan: running')).toBeInTheDocument())
  expect(fetchMock.mock.calls.some(([, i]) => i?.method === 'POST')).toBe(true)
})

test('Plan on a plan awaiting approval opens the card with the plan expanded', async () => {
  mockApi({
    '/api/cards': { body: [card('AB-1')] },
    '/api/plans': { body: { 'AB-1': 'ready' } },
    '/api/implementations': { body: {} },
    '/api/ai-config': { body: withRepo },
  })
  render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/cards/:key" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  )
  await userEvent.click(await screen.findByRole('button', { name: 'Plan' }))
  expect(await screen.findByText('/cards/AB-1?open=plan')).toBeInTheDocument()
})

test('buttons are disabled when the project has no repo', async () => {
  mockApi({
    '/api/cards': { body: [card('AB-1')] },
    '/api/plans': { body: {} },
    '/api/implementations': { body: {} },
    '/api/ai-config': { body: config },
  })
  renderHome()
  await screen.findByRole('link', { name: /AB-1/ })
  expect(enabled('Plan')).toBeDisabled()
})

test('has the CAIrdboard title and no summary text', async () => {
  mockApi({ '/api/cards': { body: [] } })
  renderHome()
  expect(screen.getByRole('heading', { level: 1, name: 'CAIrdboard' })).toBeInTheDocument()
  expect(screen.queryByText(/Review the Jira cards assigned to you/)).not.toBeInTheDocument()
})

test('cards with a plan are In Progress; the rest are To Do', async () => {
  mockApi({
    '/api/cards': { body: [card('AB-1'), card('AB-2'), card('AB-3')] },
    '/api/plans': { body: { 'AB-2': 'ready', 'AB-3': 'failed' } },
    '/api/ai-config': { body: config },
  })
  renderHome()
  await screen.findByRole('link', { name: /AB-1/ })
  const inProgress = within(screen.getByRole('region', { name: 'In Progress' }))
  const todo = within(screen.getByRole('region', { name: 'To Do' }))
  expect(inProgress.getAllByRole('link').map((l) => l.getAttribute('href'))).toEqual(['/cards/AB-2', '/cards/AB-3'])
  expect(todo.getAllByRole('link').map((l) => l.getAttribute('href'))).toEqual(['/cards/AB-1'])
})

test('an empty section says so', async () => {
  mockApi({ '/api/cards': { body: [card('AB-1')] }, '/api/plans': { body: {} } })
  renderHome()
  await screen.findByRole('link', { name: /AB-1/ })
  expect(within(screen.getByRole('region', { name: 'In Progress' })).getByText('No cards.')).toBeInTheDocument()
})

test('every ineligible card, planned or not, goes under In Review/Done', async () => {
  mockApi({
    '/api/cards': {
      body: [card('AB-1'), card('AB-2', { status: 'Testing on Dev' }), card('AB-3', { status: 'Testing on Dev' })],
    },
    '/api/plans': { body: { 'AB-3': 'approved' } },
    '/api/ai-config': { body: config },
  })
  renderHome()
  await screen.findByRole('link', { name: /AB-1/ })
  const hrefs = (name: string) =>
    within(screen.getByRole('region', { name })).getAllByRole('link').map((l) => l.getAttribute('href'))
  expect(hrefs('To Do')).toEqual(['/cards/AB-1'])
  expect(hrefs('In Review/Done')).toEqual(['/cards/AB-2', '/cards/AB-3'])
  expect(screen.getByRole('region', { name: 'In Progress' })).toHaveTextContent('No cards.')
})

test('the In Review/Done section is hidden when empty', async () => {
  mockApi({ '/api/cards': { body: [card('AB-1')] }, '/api/plans': { body: {} }, '/api/ai-config': { body: config } })
  renderHome()
  await screen.findByRole('link', { name: /AB-1/ })
  expect(screen.queryByRole('region', { name: 'In Review/Done' })).not.toBeInTheDocument()
})

test('a clean review unlocks the Test step, and a running app shows a check', async () => {
  mockApi({
    '/api/cards': { body: [card('AB-1'), card('AB-2')] },
    '/api/plans': { body: { 'AB-1': 'approved', 'AB-2': 'approved' } },
    '/api/implementations': { body: { 'AB-1': 'completed', 'AB-2': 'completed' } },
    '/api/reviews': { body: { 'AB-1': 'clean', 'AB-2': 'clean' } },
    '/api/tests': { body: { 'AB-2': 'running' } },
    '/api/ai-config': { body: withRepo },
  })
  renderHome()
  expect(await screen.findByText('Test: available')).toBeInTheDocument()
  expect(screen.getByText('Test: running')).toBeInTheDocument()
  expect(screen.getAllByRole('button', { name: 'Test' })).toHaveLength(1)
  expect(screen.getAllByRole('img', { name: 'Test' })).toHaveLength(1)
})

test('Test is disabled until the review is clean', async () => {
  mockApi({
    '/api/cards': { body: [card('AB-1')] },
    '/api/plans': { body: { 'AB-1': 'approved' } },
    '/api/implementations': { body: { 'AB-1': 'completed' } },
    '/api/reviews': { body: { 'AB-1': 'fixed' } },
    '/api/ai-config': { body: withRepo },
  })
  renderHome()
  expect(await screen.findByRole('button', { name: 'Test' })).toBeDisabled()
})

test('clicking Test starts the manual test', async () => {
  const fetchMock = mockApi({
    '/api/cards': { body: [card('AB-1')] },
    '/api/plans': { body: { 'AB-1': 'approved' } },
    '/api/implementations': { body: { 'AB-1': 'completed' } },
    '/api/reviews': { body: { 'AB-1': 'clean' } },
    '/api/ai-config': { body: withRepo },
    'POST /api/cards/AB-1/test': { status: 202, body: { state: 'preparing' } },
  })
  renderHome()
  await userEvent.click(await screen.findByRole('button', { name: 'Test' }))
  await vi.waitFor(() => expect(screen.getByText('Test: preparing')).toBeInTheDocument())
  expect(fetchMock).toHaveBeenCalledWith('/api/cards/AB-1/test', expect.objectContaining({ method: 'POST' }))
})
