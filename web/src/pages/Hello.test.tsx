import { render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import Hello from './Hello'

afterEach(() => vi.unstubAllGlobals())

test('shows the message returned by the API', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ ok: true, json: async () => ({ message: 'Hello, world!' }) }),
  )
  render(<Hello />)
  expect(await screen.findByRole('heading', { name: 'Hello, world!' })).toBeInTheDocument()
})

test('shows an error when the API fails', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500 }))
  render(<Hello />)
  expect(await screen.findByRole('alert')).toHaveTextContent('Request failed: 500')
})
