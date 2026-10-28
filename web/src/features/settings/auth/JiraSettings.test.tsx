import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import Settings from './JiraSettings'

afterEach(() => vi.unstubAllGlobals())

const ok = (body: unknown) => ({ ok: true, json: async () => body })
const status = (over = {}) => ({
  configured: true,
  connected: true,
  user: 'Me',
  base_url: 'https://a.atlassian.net',
  email: 'me@x.com',
  ...over,
})
const empty = status({ configured: false, connected: false, user: null, base_url: '', email: '' })

test('prefills site and email but never the token', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(ok(status())))
  render(<Settings />)
  expect(await screen.findByLabelText('Jira site URL')).toHaveValue('https://a.atlassian.net')
  expect(screen.getByLabelText('Jira email')).toHaveValue('me@x.com')
  expect(screen.getByLabelText('Jira API token')).toHaveValue('')
  expect(screen.getByText('Connected to Jira as Me.')).toBeInTheDocument()
})

test('Save is disabled until something changes', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(ok(status())))
  render(<Settings />)
  await screen.findByText('Connected to Jira as Me.')
  const save = screen.getByRole('button', { name: 'Save' })
  expect(save).toBeDisabled()
  await userEvent.type(screen.getByLabelText('Jira API token'), 'k')
  expect(save).toBeEnabled()
})

test('sends only the changed fields', async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(ok(status()))
    .mockResolvedValueOnce(ok({ connected: true, user: 'Me' }))
    .mockResolvedValueOnce(ok(status({ email: 'new@x.com' })))
  vi.stubGlobal('fetch', fetchMock)
  render(<Settings />)
  const emailInput = await screen.findByLabelText('Jira email')
  await userEvent.clear(emailInput)
  await userEvent.type(emailInput, 'new@x.com')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))

  expect(await screen.findByRole('status')).toHaveTextContent('Connected as Me')
  const [url, init] = fetchMock.mock.calls[1]
  expect(url).toBe('/api/jira/credentials')
  expect(init.method).toBe('PUT')
  expect(JSON.parse(init.body)).toEqual({ email: 'new@x.com' })
})

test('sends all fields on first-time setup and clears the token box', async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(ok(empty))
    .mockResolvedValueOnce(ok({ connected: true, user: 'Me' }))
    .mockResolvedValueOnce(ok(status()))
  vi.stubGlobal('fetch', fetchMock)
  render(<Settings />)
  await userEvent.type(await screen.findByLabelText('Jira site URL'), 'https://a.atlassian.net')
  await userEvent.type(screen.getByLabelText('Jira email'), 'me@x.com')
  await userEvent.type(screen.getByLabelText('Jira API token'), 'abc')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))

  await screen.findByRole('status')
  expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
    base_url: 'https://a.atlassian.net',
    email: 'me@x.com',
    token: 'abc',
  })
  expect(screen.getByLabelText('Jira API token')).toHaveValue('')
})

test('shows the server error when credentials are rejected', async () => {
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValueOnce(ok(status()))
      .mockResolvedValueOnce({ ok: false, status: 400, json: async () => ({ detail: 'Jira did not accept these credentials' }) }),
  )
  render(<Settings />)
  await userEvent.type(await screen.findByLabelText('Jira API token'), 'bad')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('did not accept')
})

test('formats validation errors from the API', async () => {
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValueOnce(ok(status()))
      .mockResolvedValueOnce({ ok: false, status: 422, json: async () => ({ detail: [{ msg: 'Must start with http' }] }) }),
  )
  render(<Settings />)
  await userEvent.type(await screen.findByLabelText('Jira API token'), 'x')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Must start with http')
})

test('typing before the status loads is not overwritten', async () => {
  let resolve!: (v: unknown) => void
  vi.stubGlobal('fetch', vi.fn().mockReturnValue(new Promise((r) => (resolve = r))))
  render(<Settings />)
  await userEvent.type(screen.getByLabelText('Jira email'), 'typed@x.com')
  resolve(ok(status({ email: 'saved@x.com' })))
  await screen.findByText('Connected to Jira as Me.')
  expect(screen.getByLabelText('Jira email')).toHaveValue('typed@x.com')
  expect(screen.getByLabelText('Jira site URL')).toHaveValue('https://a.atlassian.net')
})

test('prompts for setup when not configured', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(ok(empty)))
  render(<Settings />)
  expect(await screen.findByText(/Enter your Jira site/)).toBeInTheDocument()
})
