import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import Cards from './Cards'

afterEach(() => vi.unstubAllGlobals())

const card = (key: string, priority: string | null = 'High') => ({
  key,
  summary: `Summary ${key}`,
  status: 'To Do',
  priority,
  url: `https://x.atlassian.net/browse/${key}`,
})

test('lists cards returned by the API', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ ok: true, json: async () => [card('AB-1'), card('AB-2', null)] }),
  )
  render(
    <MemoryRouter>
      <Cards />
    </MemoryRouter>,
  )
  expect(await screen.findByRole('link', { name: 'AB-1' })).toHaveAttribute(
    'href',
    'https://x.atlassian.net/browse/AB-1',
  )
  expect(screen.getByText(/Summary AB-2/)).toBeInTheDocument()
  expect(screen.getAllByText('High')).toHaveLength(1)
  expect(screen.getAllByText('To Do')).toHaveLength(2)
})

test('shows an empty state', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => [] }))
  render(
    <MemoryRouter>
      <Cards />
    </MemoryRouter>,
  )
  expect(await screen.findByText('No cards assigned to you.')).toBeInTheDocument()
})

test('shows the server error detail', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ ok: false, status: 503, json: async () => ({ detail: 'Jira is not configured' }) }),
  )
  render(
    <MemoryRouter>
      <Cards />
    </MemoryRouter>,
  )
  expect(await screen.findByRole('alert')).toHaveTextContent('Jira is not configured')
})

test('Sync button refetches cards', async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce({ ok: true, json: async () => [card('AB-1')] })
    .mockResolvedValueOnce({ ok: true, json: async () => [card('AB-1'), card('AB-3')] })
  vi.stubGlobal('fetch', fetchMock)
  render(
    <MemoryRouter>
      <Cards />
    </MemoryRouter>,
  )
  await screen.findByRole('link', { name: 'AB-1' })
  await userEvent.click(screen.getByRole('button', { name: 'Sync' }))
  expect(await screen.findByRole('link', { name: 'AB-3' })).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledTimes(2)
})
