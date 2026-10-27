import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { changes, feedbackComment, feedbackRun, mockApi } from '../test-utils'
import Changes from './Changes'

afterEach(() => vi.unstubAllGlobals())

function renderChanges() {
  render(
    <MemoryRouter initialEntries={['/cards/AB-1/changes']}>
      <Routes>
        <Route path="/cards/:key/changes" element={<Changes />} />
      </Routes>
    </MemoryRouter>,
  )
}

const EMPTY = { body: { comments: [], run: null } }
const submitButton = () => screen.getByRole('button', { name: 'Submit for changes' })
const bodyOf = (fetchMock: ReturnType<typeof mockApi>, method: string) =>
  JSON.parse(fetchMock.mock.calls.find(([, i]) => i?.method === method)![1]!.body as string)

test('Submit for changes is disabled until a comment exists', async () => {
  mockApi({
    '/api/cards/AB-1/changes': { body: changes() },
    '/api/cards/AB-1/feedback': EMPTY,
    'POST /api/cards/AB-1/feedback/comments': { status: 201, body: feedbackComment('c1', { text: 'Rename it' }) },
  })
  renderChanges()
  await screen.findByText('3 files changed,')
  expect(submitButton()).toBeDisabled()
  await userEvent.type(screen.getByLabelText('General comment'), 'Rename it')
  await userEvent.click(screen.getByRole('button', { name: 'Add comment' }))
  const panel = within(screen.getByRole('complementary', { name: 'Review feedback' }))
  expect(await panel.findByText('Rename it')).toBeInTheDocument()
  expect(panel.getByText('General')).toBeInTheDocument()
  expect(panel.getByText('Pending comments (1)')).toBeInTheDocument()
  expect(submitButton()).toBeEnabled()
  expect(screen.getByLabelText('General comment')).toHaveValue('')
})

test('comments on an added or changed line, and on a removed line', async () => {
  const fetchMock = mockApi({
    '/api/cards/AB-1/changes': { body: changes() },
    '/api/cards/AB-1/feedback': EMPTY,
    'POST /api/cards/AB-1/feedback/comments': {
      status: 201,
      body: feedbackComment('c1', { text: 'Why?', file: 'src/a.ts', line: 2, code: 'new line' }),
    },
  })
  renderChanges()
  await userEvent.click(await screen.findByRole('button', { name: 'Comment on line 2' }))
  await userEvent.type(screen.getByLabelText('Your comment on line 2'), 'Why?')
  const pane = within(screen.getByLabelText('File diff'))
  await userEvent.click(pane.getByRole('button', { name: 'Add comment' }))
  expect(bodyOf(fetchMock, 'POST')).toEqual({
    text: 'Why?',
    file: 'src/a.ts',
    line: 2,
    side: 'new',
    code: 'new line',
  })
  // The comment now shows under its line and in the panel; the composer is closed.
  expect(await pane.findByText('Why?')).toBeInTheDocument()
  expect(screen.queryByLabelText('Your comment on line 2')).not.toBeInTheDocument()
  expect(within(screen.getByRole('complementary')).getByText('src/a.ts:2')).toBeInTheDocument()
  expect(submitButton()).toBeEnabled()

  expect(screen.getByRole('button', { name: 'Comment on removed line 2' })).toBeInTheDocument()
})

test('line comments are not offered while viewing a single commit', async () => {
  mockApi({
    '/api/cards/AB-1/changes': { body: changes() },
    '/api/cards/AB-1/changes?commit=bbbbbbb2222': { body: changes({ selected_commit: 'bbbbbbb2222' }) },
    '/api/cards/AB-1/feedback': EMPTY,
  })
  renderChanges()
  await screen.findByRole('button', { name: 'Comment on line 2' })
  await userEvent.click(screen.getByRole('combobox', { name: 'Commits' }))
  await userEvent.click(await screen.findByRole('option', { name: /null check/ }))
  await screen.findByText('new line')
  await vi.waitFor(() => expect(screen.queryByRole('button', { name: 'Comment on line 2' })).not.toBeInTheDocument())
  // General comments still work.
  expect(screen.getByLabelText('General comment')).toBeInTheDocument()
})

test('edit and delete a pending comment', async () => {
  const fetchMock = mockApi({
    '/api/cards/AB-1/changes': { body: changes() },
    '/api/cards/AB-1/feedback': { body: { comments: [feedbackComment('c1', { text: 'First' })], run: null } },
    'PUT /api/cards/AB-1/feedback/comments/c1': { body: feedbackComment('c1', { text: 'Second' }) },
    'DELETE /api/cards/AB-1/feedback/comments/c1': { status: 204, body: null },
  })
  renderChanges()
  await screen.findByText('First')
  await userEvent.click(screen.getByRole('button', { name: 'Edit comment' }))
  const box = screen.getByLabelText('Edit comment')
  await userEvent.clear(box)
  await userEvent.type(box, 'Second')
  await userEvent.click(screen.getByRole('button', { name: 'Save comment' }))
  expect(await screen.findByText('Second')).toBeInTheDocument()
  expect(bodyOf(fetchMock, 'PUT')).toEqual({ text: 'Second' })

  await userEvent.click(screen.getByRole('button', { name: 'Delete comment' }))
  await vi.waitFor(() => expect(screen.queryByText('Second')).not.toBeInTheDocument())
  expect(submitButton()).toBeDisabled()
})

test('submitting starts the run and locks the button while it runs', async () => {
  const fetchMock = mockApi({
    '/api/cards/AB-1/changes': { body: changes() },
    '/api/cards/AB-1/feedback': { body: { comments: [feedbackComment('c1')], run: null } },
    'POST /api/cards/AB-1/feedback/submit': { status: 202, body: feedbackRun() },
  })
  renderChanges()
  await screen.findByText('Comment c1')
  await userEvent.click(submitButton())
  expect(await screen.findByText(/An AI is making the requested changes/)).toBeInTheDocument()
  expect(submitButton()).toBeDisabled()
  expect(fetchMock.mock.calls.some(([u, i]) => u.endsWith('/feedback/submit') && i?.method === 'POST')).toBe(true)
})

test('a finished run shows its result, report and the resolved comments', async () => {
  mockApi({
    '/api/cards/AB-1/changes': { body: changes() },
    '/api/cards/AB-1/feedback': {
      body: {
        comments: [feedbackComment('c1', { status: 'resolved', resolved_in: 1, text: 'Old note' })],
        run: feedbackRun({
          state: 'done',
          commits: [{ sha: 'a', short: 'a', subject: 'x' }],
          report: '## Feedback summary\nAll done',
        }),
      },
    },
  })
  renderChanges()
  expect(await screen.findByText(/Changes made \(1 commit\)/)).toBeInTheDocument()
  expect(screen.getByText('Pending comments (0)')).toBeInTheDocument()
  expect(submitButton()).toBeDisabled()
  await userEvent.click(screen.getByRole('button', { name: 'Resolved (1)' }))
  expect(await screen.findByText('Old note')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Agent report' }))
  expect(await screen.findByText(/All done/)).toBeInTheDocument()
})

test('a failed run shows its error and keeps submit available', async () => {
  mockApi({
    '/api/cards/AB-1/changes': { body: changes() },
    '/api/cards/AB-1/feedback': {
      body: { comments: [feedbackComment('c1')], run: feedbackRun({ state: 'failed', error: 'boom' }) },
    },
  })
  renderChanges()
  expect(await screen.findByText('boom')).toBeInTheDocument()
  expect(submitButton()).toBeEnabled()
})

test('shows a submit error from the server', async () => {
  mockApi({
    '/api/cards/AB-1/changes': { body: changes() },
    '/api/cards/AB-1/feedback': { body: { comments: [feedbackComment('c1')], run: null } },
    'POST /api/cards/AB-1/feedback/submit': { status: 409, body: { detail: 'Another run is in progress' } },
  })
  renderChanges()
  await screen.findByText('Comment c1')
  await userEvent.click(submitButton())
  expect(await screen.findByRole('alert')).toHaveTextContent('Another run is in progress')
})
