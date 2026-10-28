import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import { card, mockApi } from '../../test-utils'
import Archive from './Archive'

afterEach(() => vi.unstubAllGlobals())

function renderArchive() {
  render(
    <MemoryRouter>
      <Archive />
    </MemoryRouter>,
  )
}

test('lists only archived cards, linking to their detail page', async () => {
  mockApi({
    '/api/cards': { body: [card('AB-1'), card('AB-2', { status: 'Done' })] },
    '/api/archive': { body: ['AB-2'] },
  })
  renderArchive()
  expect(await screen.findByRole('link', { name: 'AB-2' })).toHaveAttribute('href', '/cards/AB-2')
  expect(screen.getByText('Summary AB-2')).toBeInTheDocument()
  expect(screen.queryByText('AB-1')).not.toBeInTheDocument()
})

test('Unarchive calls the API and removes the card from the list', async () => {
  const fetchMock = mockApi({
    '/api/cards': { body: [card('AB-2', { status: 'Done' })] },
    '/api/archive': { body: ['AB-2'] },
    'DELETE /api/cards/AB-2/archive': { status: 204 },
  })
  renderArchive()
  await userEvent.click(await screen.findByRole('button', { name: 'Unarchive AB-2' }))
  await waitFor(() => expect(screen.getByText('No archived cards.')).toBeInTheDocument())
  expect(fetchMock).toHaveBeenCalledWith('/api/cards/AB-2/archive', { method: 'DELETE' })
})

test('shows an error when the archive cannot be loaded', async () => {
  mockApi({ '/api/cards': { body: [] }, '/api/archive': { status: 500, body: { detail: 'boom' } } })
  renderArchive()
  expect(await screen.findByRole('alert')).toHaveTextContent('boom')
})
