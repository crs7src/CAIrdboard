import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import App from './App'
import { mockApi } from './test-utils'

afterEach(() => vi.unstubAllGlobals())

function renderAt(path: string) {
  mockApi({
    '/api/ai-config': { body: { eligible_statuses: [], project_repos: {} } },
    '/api/cards': { body: [] },
    '/api/jira/status': { body: { base_url: '', email: '', configured: false, connected: false } },
  })
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
  expect(screen.queryByRole('link', { name: 'My Cards' })).toBeNull()
  expect(screen.getByRole('link', { name: 'Settings' })).toHaveAttribute('href', '/settings')
})

test('the Projects nav link opens the projects page', async () => {
  renderAt('/')
  mockApi({ '/api/projects': { body: [] }, '/api/cards': { body: [] } })
  expect(screen.getByRole('link', { name: 'Projects' })).toHaveAttribute('href', '/projects')
  await userEvent.click(screen.getByRole('link', { name: 'Projects' }))
  expect(await screen.findByRole('heading', { name: 'Projects' })).toBeInTheDocument()
})

test('the title in the header navigates home', async () => {
  renderAt('/settings/jira')
  await userEvent.click(screen.getByRole('link', { name: 'CAIrdboard' }))
  expect(await screen.findByRole('heading', { level: 1, name: 'CAIrdboard' })).toBeInTheDocument()
})

test('clicking a nav link switches the page', async () => {
  renderAt('/')
  await userEvent.click(screen.getByRole('link', { name: 'Settings' }))
  expect(await screen.findByRole('heading', { name: 'Settings' })).toBeInTheDocument()
  expect(screen.getByRole('tab', { name: 'AI' })).toHaveAttribute('aria-selected', 'true')
})

test('AI settings is a tab under Settings and the old URL redirects', async () => {
  renderAt('/ai-settings')
  expect(await screen.findByRole('heading', { name: 'AI planning' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Settings' })).toBeInTheDocument()
  expect(screen.getByRole('tab', { name: 'AI' })).toHaveAttribute('aria-selected', 'true')
  expect(screen.queryByRole('link', { name: 'AI Settings' })).toBeNull()

  await userEvent.click(screen.getByRole('tab', { name: 'Jira' }))
  expect(await screen.findByRole('heading', { name: 'Jira connection' })).toBeInTheDocument()
  expect(screen.getByRole('tab', { name: 'Jira' })).toHaveAttribute('aria-selected', 'true')
})

test('Settings has a Skills tab', async () => {
  renderAt('/settings/skills')
  expect(await screen.findByRole('tab', { name: 'Skills' })).toHaveAttribute('aria-selected', 'true')
})
