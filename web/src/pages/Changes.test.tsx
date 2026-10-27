import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { changes, mockApi } from '../test-utils'
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

test('lists changed files with status and line counts, and shows each diff', async () => {
  mockApi({ '/api/cards/AB-1/changes': { body: changes() } })
  renderChanges()
  expect(await screen.findByText('3 files changed,')).toBeInTheDocument()
  expect(screen.getByText('AB-1_add_dark_mode')).toBeInTheDocument()

  const list = within(screen.getByRole('list', { name: 'Changed files' }))
  expect(list.getByText('src/a.ts')).toBeInTheDocument()
  expect(list.getByText('src/new.ts')).toBeInTheDocument()
  expect(list.getByText('gone.txt')).toBeInTheDocument()

  // Only the first file is shown; the others appear when selected.
  const pane = within(screen.getByLabelText('File diff'))
  expect(pane.getByText('modified')).toBeInTheDocument()
  expect(pane.getByText('new line')).toBeInTheDocument()
  expect(pane.getByText('old line')).toBeInTheDocument()
  expect(screen.queryByText('one')).not.toBeInTheDocument()
  expect(screen.queryByText('bye')).not.toBeInTheDocument()

  await userEvent.click(list.getByText('src/new.ts'))
  expect(screen.getByText('added')).toBeInTheDocument()
  expect(screen.getByText('two')).toBeInTheDocument()
  expect(screen.queryByText('new line')).not.toBeInTheDocument()

  await userEvent.click(list.getByText('gone.txt'))
  expect(screen.getByText('deleted')).toBeInTheDocument()
  expect(screen.getByText('bye')).toBeInTheDocument()
  expect(screen.getByText(/^\+3$/)).toBeInTheDocument()
  expect(screen.getByText(/^−2$/)).toBeInTheDocument()
})

test('shows one commit at a time through the commit picker', async () => {
  const fetchMock = mockApi({
    '/api/cards/AB-1/changes': { body: changes() },
    '/api/cards/AB-1/changes?commit=bbbbbbb2222': {
      body: changes({
        selected_commit: 'bbbbbbb2222',
        diff: 'diff --git a/only.ts b/only.ts\n--- a/only.ts\n+++ b/only.ts\n@@ -1 +1 @@\n-a\n+b\n',
      }),
    },
  })
  renderChanges()
  await screen.findByText('3 files changed,')
  await userEvent.click(screen.getByRole('combobox', { name: 'Commits' }))
  await userEvent.click(await screen.findByRole('option', { name: /bbbbbbb AB-1: review fix/ }))
  expect(await screen.findByText('1 file changed,')).toBeInTheDocument()
  expect(fetchMock.mock.calls.map(([u]) => String(u))).toContain('/api/cards/AB-1/changes?commit=bbbbbbb2222')
  // The picker still offers every commit while one is selected.
  await userEvent.click(screen.getByRole('combobox', { name: 'Commits' }))
  expect(await screen.findByRole('option', { name: /All changes \(2 commits\)/ })).toBeInTheDocument()
})

test('shows an empty state when there are no changes', async () => {
  mockApi({ '/api/cards/AB-1/changes': { body: changes({ diff: '', commits: [] }) } })
  renderChanges()
  expect(await screen.findByText('No changes to show.')).toBeInTheDocument()
})

test('shows the server error and a link back to the card', async () => {
  mockApi({ '/api/cards/AB-1/changes': { status: 404, body: { detail: 'No implementation branch exists for this card' } } })
  renderChanges()
  expect(await screen.findByRole('alert')).toHaveTextContent('No implementation branch')
  expect(screen.getByRole('link', { name: 'Back to AB-1' })).toHaveAttribute('href', '/cards/AB-1')
})
