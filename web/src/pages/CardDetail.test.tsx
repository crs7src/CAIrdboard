import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { card, mockApi, plan } from '../test-utils'
import CardDetail, { POLL_MS } from './CardDetail'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const detail = (over = {}) => card('AB-1', { eligible: true, repo_configured: true, ...over })
const NO_PLAN = { status: 404, body: { detail: 'No plan exists for this card' } }

function renderDetail() {
  render(
    <MemoryRouter initialEntries={['/cards/AB-1']}>
      <Routes>
        <Route path="/cards/:key" element={<CardDetail />} />
      </Routes>
    </MemoryRouter>,
  )
}

test('shows card details and a Generate button when there is no plan', async () => {
  mockApi({ '/api/cards/AB-1': { body: detail() }, '/api/cards/AB-1/plan': NO_PLAN })
  renderDetail()
  expect(await screen.findByRole('heading', { name: 'AB-1' })).toBeInTheDocument()
  expect(screen.getByText('Summary AB-1')).toBeInTheDocument()
  expect(screen.getByText('Description of AB-1')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Open in Jira' })).toHaveAttribute(
    'href',
    'https://x.atlassian.net/browse/AB-1',
  )
  expect(screen.getByRole('button', { name: 'Generate plan' })).toBeInTheDocument()
})

test('shows the card comments with authors', async () => {
  const comments = [
    { author: 'Ann', created: '2026-01-02T10:00:00.000+0000', body: 'Button is the wrong color' },
    { author: 'Bob', created: '2026-01-03T10:00:00.000+0000', body: 'Also fix the label' },
  ]
  mockApi({ '/api/cards/AB-1': { body: detail({ comments }) }, '/api/cards/AB-1/plan': NO_PLAN })
  renderDetail()
  expect(await screen.findByText('Comments (2)')).toBeInTheDocument()
  expect(screen.getByText('Button is the wrong color')).toBeInTheDocument()
  expect(screen.getByText(/Bob/)).toBeInTheDocument()
})

test('flags a card that was reopened earlier and marks newer comments', async () => {
  mockApi({
    '/api/cards/AB-1': {
      body: detail({
        status: 'In Progress',
        reopened: true,
        last_reopened_at: '2026-01-02T09:00:00.000+0000',
        status_history: [
          { from_status: 'Done', to_status: 'Reopened', when: '2026-01-02T09:00:00.000+0000', author: 'Ann' },
          { from_status: 'Reopened', to_status: 'In Progress', when: '2026-01-03T09:00:00.000+0000', author: 'Bob' },
        ],
        comments: [{ author: 'Ann', created: '2026-01-02T10:00:00.000+0000', body: 'Fix it', after_reopen: true }],
      }),
    },
    '/api/cards/AB-1/plan': NO_PLAN,
  })
  renderDetail()
  expect(await screen.findByText('Reopened before')).toBeInTheDocument()
  expect(screen.getByText('after reopen')).toBeInTheDocument()
  expect(screen.getByText(/Done → Reopened, Reopened → In Progress/)).toBeInTheDocument()
})

test('does not flag a card that was never reopened', async () => {
  mockApi({ '/api/cards/AB-1': { body: detail() }, '/api/cards/AB-1/plan': NO_PLAN })
  renderDetail()
  await screen.findByText('Comments (0)')
  expect(screen.queryByText('Reopened before')).not.toBeInTheDocument()
})

test('shows an empty state when the card has no comments', async () => {
  mockApi({ '/api/cards/AB-1': { body: detail() }, '/api/cards/AB-1/plan': NO_PLAN })
  renderDetail()
  expect(await screen.findByText('Comments (0)')).toBeInTheDocument()
  expect(screen.getByText('No comments.')).toBeInTheDocument()
})

test('ineligible card explains why and offers no Generate button', async () => {
  mockApi({
    '/api/cards/AB-1': { body: detail({ status: 'Testing', eligible: false }) },
    '/api/cards/AB-1/plan': NO_PLAN,
  })
  renderDetail()
  expect(await screen.findByText(/not generated for cards in "Testing"/)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Generate plan' })).not.toBeInTheDocument()
})

test('missing repo mapping links to AI settings and hides Generate', async () => {
  mockApi({
    '/api/cards/AB-1': { body: detail({ repo_configured: false }) },
    '/api/cards/AB-1/plan': NO_PLAN,
  })
  renderDetail()
  expect(await screen.findByText(/No repo is configured for project AB/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'AI Settings' })).toHaveAttribute('href', '/settings/ai')
  expect(screen.queryByRole('button', { name: 'Generate plan' })).not.toBeInTheDocument()
})

test('Generate posts to the API and shows the running state', async () => {
  const fetchMock = mockApi({
    '/api/cards/AB-1': { body: detail() },
    '/api/cards/AB-1/plan': NO_PLAN,
    'POST /api/cards/AB-1/plan': { status: 202, body: plan({ state: 'running', plan: null }) },
  })
  renderDetail()
  await userEvent.click(await screen.findByRole('button', { name: 'Generate plan' }))
  expect(await screen.findByText('Generating plan...')).toBeInTheDocument()
  const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')!
  expect(JSON.parse(post[1]!.body as string)).toEqual({ feedback: null })
})

test('polls while running and renders the markdown plan when ready', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  mockApi({
    '/api/cards/AB-1': { body: detail() },
    '/api/cards/AB-1/plan': [
      { body: plan({ state: 'running', plan: null }) },
      { body: plan({ state: 'ready' }) },
    ],
  })
  renderDetail()
  await screen.findByText('Generating plan...')
  await vi.advanceTimersByTimeAsync(POLL_MS + 100)
  expect(await screen.findByRole('heading', { name: 'Steps' })).toBeInTheDocument()
  expect(screen.getByText('Do the thing')).toBeInTheDocument()
  expect(screen.queryByText('Generating plan...')).not.toBeInTheDocument()
})

test('Approve records the decision', async () => {
  mockApi({
    '/api/cards/AB-1': { body: detail() },
    '/api/cards/AB-1/plan': { body: plan() },
    'POST /api/cards/AB-1/plan/approve': { body: plan({ state: 'approved' }) },
  })
  renderDetail()
  await userEvent.click(await screen.findByRole('button', { name: 'Approve' }))
  expect(await screen.findByText('approved')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
})

test('Reject records the decision', async () => {
  mockApi({
    '/api/cards/AB-1': { body: detail() },
    '/api/cards/AB-1/plan': { body: plan() },
    'POST /api/cards/AB-1/plan/reject': { body: plan({ state: 'rejected' }) },
  })
  renderDetail()
  await userEvent.click(await screen.findByRole('button', { name: 'Reject' }))
  expect(await screen.findByText('rejected')).toBeInTheDocument()
})

test('Regenerate sends the typed feedback', async () => {
  const fetchMock = mockApi({
    '/api/cards/AB-1': { body: detail() },
    '/api/cards/AB-1/plan': { body: plan({ state: 'rejected' }) },
    'POST /api/cards/AB-1/plan': {
      status: 202,
      body: plan({ state: 'running', plan: null, version: 2, feedback: 'Too vague' }),
    },
  })
  renderDetail()
  await userEvent.type(
    await screen.findByLabelText('What was wrong with this plan? (optional)'),
    'Too vague',
  )
  await userEvent.click(screen.getByRole('button', { name: 'Regenerate plan' }))
  expect(await screen.findByText('Generating plan...')).toBeInTheDocument()
  const post = fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')!
  expect(JSON.parse(post[1]!.body as string)).toEqual({ feedback: 'Too vague' })
})

test('failed plan shows the error and can be retried', async () => {
  mockApi({
    '/api/cards/AB-1': { body: detail() },
    '/api/cards/AB-1/plan': { body: plan({ state: 'failed', plan: null, error: 'boom' }) },
  })
  renderDetail()
  expect(await screen.findByRole('alert')).toHaveTextContent('boom')
  expect(screen.getByRole('button', { name: 'Regenerate plan' })).toBeInTheDocument()
})

test('shows a server error when generating is refused', async () => {
  mockApi({
    '/api/cards/AB-1': { body: detail() },
    '/api/cards/AB-1/plan': NO_PLAN,
    'POST /api/cards/AB-1/plan': { status: 409, body: { detail: 'Already generating' } },
  })
  renderDetail()
  await userEvent.click(await screen.findByRole('button', { name: 'Generate plan' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Already generating')
})

test('shows an error when the card cannot be loaded', async () => {
  mockApi({ '/api/cards/AB-1': { status: 404, body: { detail: 'Card AB-1 not found' } } })
  renderDetail()
  expect(await screen.findByRole('alert')).toHaveTextContent('Card AB-1 not found')
})
