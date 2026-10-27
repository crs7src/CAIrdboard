import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { card, mockApi } from '../test-utils'
import Cards from './Cards'

afterEach(() => vi.unstubAllGlobals())

const config = {
  eligible_statuses: ['To Do', 'Backlog'],
  project_repos: {},
}

function LocationProbe() {
  const { pathname, search } = useLocation()
  return <p>{pathname + search}</p>
}

function renderCards() {
  render(
    <MemoryRouter>
      <Cards />
    </MemoryRouter>,
  )
}

test('lists cards with links to their detail page', async () => {
  mockApi({
    '/api/cards': { body: [card('AB-1'), card('AB-2', { priority: null })] },
    '/api/plans': { body: {} },
    '/api/ai-config': { body: config },
  })
  renderCards()
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
  renderCards()
  await screen.findByRole('link', { name: /AB-1/ })
  const available = screen.getAllByText('Plan: available')
  expect(available.map((c) => c.closest('a')?.getAttribute('href'))).toEqual(['/cards/AB-1', '/cards/AB-3'])
})

test('the whole card is a single link to its detail page', async () => {
  mockApi({ '/api/cards': { body: [card('AB-1')] }, '/api/plans': { body: {} }, '/api/ai-config': { body: config } })
  renderCards()
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
  renderCards()
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
  renderCards()
  expect(await screen.findByText('Implementation: running')).toBeInTheDocument()
})

test('shows the plan chip while the plan is not approved', async () => {
  mockApi({
    '/api/cards': { body: [card('AB-1')] },
    '/api/plans': { body: { 'AB-1': 'ready' } },
    '/api/implementations': { body: {} },
    '/api/ai-config': { body: config },
  })
  renderCards()
  expect(await screen.findByText('Plan: ready')).toBeInTheDocument()
})

test('still lists cards if plan info fails to load', async () => {
  mockApi({ '/api/cards': { body: [card('AB-1')] } })
  renderCards()
  expect(await screen.findByRole('link', { name: /AB-1/ })).toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('shows an empty state', async () => {
  mockApi({ '/api/cards': { body: [] } })
  renderCards()
  expect(await screen.findByText('No cards assigned to you.')).toBeInTheDocument()
})

test('shows the server error detail with a link to settings', async () => {
  mockApi({
    '/api/cards': { status: 503, body: { detail: 'Jira is not configured' } },
  })
  renderCards()
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
  renderCards()
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
  renderCards()
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
  renderCards()
  expect(await screen.findByRole('img', { name: 'Plan' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Plan' })).not.toBeInTheDocument()
  expect(enabled('Implement')).toBeEnabled()
})

test('a completed implementation shows a check; review stays disabled', async () => {
  mockApi({
    '/api/cards': { body: [card('AB-1')] },
    '/api/plans': { body: { 'AB-1': 'approved' } },
    '/api/implementations': { body: { 'AB-1': 'completed' } },
    '/api/ai-config': { body: withRepo },
  })
  renderCards()
  expect(await screen.findByRole('img', { name: 'Implement' })).toBeInTheDocument()
  expect(enabled('Review')).toBeDisabled()
})

test('clicking Plan starts the plan without opening the card', async () => {
  const fetchMock = mockApi({
    '/api/cards': { body: [card('AB-1')] },
    '/api/plans': { body: {} },
    '/api/implementations': { body: {} },
    '/api/ai-config': { body: withRepo },
    'POST /api/cards/AB-1/plan': { status: 202, body: { state: 'running' } },
  })
  renderCards()
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
    <MemoryRouter initialEntries={['/cards']}>
      <Routes>
        <Route path="/cards" element={<Cards />} />
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
  renderCards()
  await screen.findByRole('link', { name: /AB-1/ })
  expect(enabled('Plan')).toBeDisabled()
})
