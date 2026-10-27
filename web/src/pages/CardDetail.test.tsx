import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { card, implementation, mockApi, plan } from '../test-utils'
import CardDetail, { POLL_MS } from './CardDetail'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const detail = (over = {}) => card('AB-1', { eligible: true, repo_configured: true, ...over })
const NO_PLAN = { status: 404, body: { detail: 'No plan exists for this card' } }

async function openPlan() {
  await userEvent.click(await screen.findByRole('button', { name: /^Plan/ }))
}

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
  expect(screen.getByRole('button', { name: 'Run plan' })).toBeInTheDocument()
  expect(screen.getByText('not started')).toBeInTheDocument()
  await openPlan()
  expect(screen.getByRole('button', { name: 'Generate plan' })).toBeInTheDocument()
})

test('plan accordion is collapsed by default', async () => {
  mockApi({ '/api/cards/AB-1': { body: detail() }, '/api/cards/AB-1/plan': { body: plan() } })
  renderDetail()
  const header = await screen.findByRole('button', { name: /^Plan/ })
  expect(header).toHaveAttribute('aria-expanded', 'false')
  await userEvent.click(header)
  expect(header).toHaveAttribute('aria-expanded', 'true')
})

test('?open=plan expands the plan section', async () => {
  mockApi({ '/api/cards/AB-1': { body: detail() }, '/api/cards/AB-1/plan': { body: plan() } })
  render(
    <MemoryRouter initialEntries={['/cards/AB-1?open=plan']}>
      <Routes>
        <Route path="/cards/:key" element={<CardDetail />} />
      </Routes>
    </MemoryRouter>,
  )
  expect(await screen.findByRole('button', { name: /^Plan/ })).toHaveAttribute('aria-expanded', 'true')
  expect(screen.getByRole('button', { name: 'Approve' })).toBeVisible()
})

test('play on a ready plan opens the accordion and focuses Approve', async () => {
  mockApi({ '/api/cards/AB-1': { body: detail() }, '/api/cards/AB-1/plan': { body: plan() } })
  renderDetail()
  await userEvent.click(await screen.findByRole('button', { name: 'Review plan' }))
  expect(screen.getByRole('button', { name: /^Plan/ })).toHaveAttribute('aria-expanded', 'true')
  expect(await screen.findByRole('button', { name: 'Approve' })).toHaveFocus()
})

test('plan play button is hidden once the plan is approved', async () => {
  mockApi({
    '/api/cards/AB-1': { body: detail() },
    '/api/cards/AB-1/plan': { body: plan({ state: 'approved' }) },
    '/api/cards/AB-1/implementation': NO_PLAN,
  })
  renderDetail()
  await screen.findByRole('button', { name: 'Start implementation' })
  expect(screen.queryByRole('button', { name: /plan$/i })).not.toBeInTheDocument()
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
  expect(screen.queryByRole('button', { name: /Generate plan|Run plan/ })).not.toBeInTheDocument()
})

test('missing repo mapping links to AI settings and hides Generate', async () => {
  mockApi({
    '/api/cards/AB-1': { body: detail({ repo_configured: false }) },
    '/api/cards/AB-1/plan': NO_PLAN,
  })
  renderDetail()
  expect(await screen.findByText(/No repo is configured for project AB/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'AI Settings' })).toHaveAttribute('href', '/settings/ai')
  expect(screen.queryByRole('button', { name: /Generate plan|Run plan/ })).not.toBeInTheDocument()
})

test('Generate posts to the API and shows the running state', async () => {
  const fetchMock = mockApi({
    '/api/cards/AB-1': { body: detail() },
    '/api/cards/AB-1/plan': NO_PLAN,
    'POST /api/cards/AB-1/plan': { status: 202, body: plan({ state: 'running', plan: null }) },
  })
  renderDetail()
  await userEvent.click(await screen.findByRole('button', { name: 'Run plan' }))
  await openPlan()
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
  await openPlan()
  await screen.findByText('Generating plan...')
  await vi.advanceTimersByTimeAsync(POLL_MS + 100)
  expect(await screen.findByRole('heading', { name: 'Steps' })).toBeInTheDocument()
  expect(screen.getByText('Do the thing')).toBeInTheDocument()
  expect(screen.queryByText('Generating plan...')).not.toBeInTheDocument()
})

test('implementation section appears only once the plan is approved', async () => {
  mockApi({
    '/api/cards/AB-1': { body: detail() },
    '/api/cards/AB-1/plan': { body: plan({ state: 'ready' }) },
  })
  renderDetail()
  await screen.findByRole('button', { name: /^Plan/ })
  expect(screen.queryByRole('heading', { name: 'Implementation' })).not.toBeInTheDocument()
  vi.unstubAllGlobals()

  mockApi({
    '/api/cards/AB-1': { body: detail() },
    '/api/cards/AB-1/plan': { body: plan({ state: 'approved' }) },
    '/api/cards/AB-1/implementation': { status: 404, body: { detail: 'none' } },
  })
  renderDetail()
  expect(await screen.findByRole('button', { name: 'Start implementation' })).toBeInTheDocument()
})

test('review section appears only once the implementation is completed', async () => {
  const base = {
    '/api/cards/AB-1': { body: detail() },
    '/api/cards/AB-1/plan': { body: plan({ state: 'approved' }) },
    '/api/cards/AB-1/review': NO_PLAN,
  }
  mockApi({ ...base, '/api/cards/AB-1/implementation': { body: implementation({ state: 'failed' }) } })
  renderDetail()
  await screen.findByRole('button', { name: 'Retry implementation' })
  expect(screen.queryByRole('heading', { name: 'Review' })).not.toBeInTheDocument()
  vi.unstubAllGlobals()

  mockApi({ ...base, '/api/cards/AB-1/implementation': { body: implementation() } })
  renderDetail()
  expect(await screen.findByRole('button', { name: 'Start review' })).toBeInTheDocument()
})

test('View changes links to the changes page once an implementation exists', async () => {
  mockApi({
    '/api/cards/AB-1': { body: detail() },
    '/api/cards/AB-1/plan': { body: plan({ state: 'approved' }) },
    '/api/cards/AB-1/implementation': { body: implementation() },
    '/api/cards/AB-1/review': NO_PLAN,
  })
  renderDetail()
  expect(await screen.findByRole('link', { name: 'View changes' })).toHaveAttribute('href', '/cards/AB-1/changes')
})

test('Approve records the decision', async () => {
  mockApi({
    '/api/cards/AB-1': { body: detail() },
    '/api/cards/AB-1/plan': { body: plan() },
    'POST /api/cards/AB-1/plan/approve': { body: plan({ state: 'approved' }) },
  })
  renderDetail()
  await openPlan()
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
  await openPlan()
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
  await openPlan()
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
  await openPlan()
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
  await userEvent.click(await screen.findByRole('button', { name: 'Run plan' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Already generating')
})

test('shows an error when the card cannot be loaded', async () => {
  mockApi({ '/api/cards/AB-1': { status: 404, body: { detail: 'Card AB-1 not found' } } })
  renderDetail()
  expect(await screen.findByRole('alert')).toHaveTextContent('Card AB-1 not found')
})

test('has a back link to Home, even when the card fails to load', async () => {
  mockApi({ '/api/cards/AB-1': { body: detail() }, '/api/cards/AB-1/plan': NO_PLAN })
  renderDetail()
  expect(await screen.findByRole('link', { name: 'Back to Home' })).toHaveAttribute('href', '/')
  vi.unstubAllGlobals()
  mockApi({ '/api/cards/AB-1': { status: 404, body: { detail: 'nope' } } })
  renderDetail()
  expect(await screen.findAllByRole('link', { name: 'Back to Home' })).toHaveLength(2)
})

test('comments are collapsed by default', async () => {
  mockApi({ '/api/cards/AB-1': { body: detail() }, '/api/cards/AB-1/plan': NO_PLAN })
  renderDetail()
  expect(await screen.findByRole('button', { name: /^Comments/ })).toHaveAttribute('aria-expanded', 'false')
})
