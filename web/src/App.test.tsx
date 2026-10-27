import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import App from './App'

afterEach(() => vi.unstubAllGlobals())

function renderAt(path: string) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ base_url: '', email: '', configured: false }),
    }),
  )
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  )
}

test('nav bar links to every page', () => {
  renderAt('/')
  const nav = screen.getByRole('navigation')
  expect(nav).toHaveTextContent('Home')
  expect(screen.getByRole('link', { name: 'My Cards' })).toHaveAttribute('href', '/cards')
  expect(screen.getByRole('link', { name: 'Settings' })).toHaveAttribute('href', '/settings')
})

test('clicking a nav link switches the page', async () => {
  renderAt('/')
  await userEvent.click(screen.getByRole('link', { name: 'Settings' }))
  expect(await screen.findByRole('heading', { name: 'Settings' })).toBeInTheDocument()
})
