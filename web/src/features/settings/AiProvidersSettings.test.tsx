import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { mockApi } from '../../test-utils'
import AiProvidersSettings from './AiProvidersSettings'

afterEach(() => vi.unstubAllGlobals())

const provider = (id: string, label: string, over = {}) => ({
  id,
  label,
  configured: false,
  model: id === 'copilot' ? null : `${id}-model`,
  default_model: id === 'copilot' ? null : `${id}-model`,
  models: ['model-a', 'model-b'],
  needs_key: id !== 'copilot',
  is_default: id === 'copilot',
  supports_agent: id === 'copilot',
  ...over,
})
const list = (anthropic = {}) => [
  provider('copilot', 'GitHub Copilot CLI', { configured: true }),
  provider('anthropic', 'Anthropic', anthropic),
  provider('gemini', 'Google Gemini'),
]

test('lists the providers; Copilot needs no key and the agent limit is explained', async () => {
  mockApi({ '/api/ai/providers': { body: list() } })
  render(<AiProvidersSettings />)
  expect(await screen.findByLabelText('Anthropic API key')).toBeInTheDocument()
  expect(screen.getByLabelText('Google Gemini API key')).toBeInTheDocument()
  expect(screen.getAllByLabelText(/API key/)).toHaveLength(2)
  expect(screen.getByText(/always use GitHub Copilot CLI for now/)).toBeInTheDocument()
  expect(screen.getByText('default')).toBeInTheDocument()
})

test('Copilot has a model dropdown and saves the chosen model', async () => {
  const fetchMock = mockApi({
    '/api/ai/providers': { body: list() },
    'PUT /api/ai/providers/copilot/credentials': { body: provider('copilot', 'GitHub Copilot CLI', { model: 'model-b' }) },
  })
  render(<AiProvidersSettings />)
  const selects = await screen.findAllByRole('combobox', { name: 'Model' })
  await userEvent.click(selects[0])
  await userEvent.click(await screen.findByRole('option', { name: 'model-b' }))
  await userEvent.click(screen.getAllByRole('button', { name: 'Save' })[0])
  expect(await screen.findByText('Saved.')).toBeInTheDocument()
  const put = fetchMock.mock.calls.find(([, i]) => i?.method === 'PUT')!
  expect(JSON.parse(String(put[1]?.body))).toEqual({ model: 'model-b' })
})

test('saves a key, clears the field and never shows the key', async () => {
  const fetchMock = mockApi({
    '/api/ai/providers': { body: list() },
    'PUT /api/ai/providers/anthropic/credentials': { body: provider('anthropic', 'Anthropic', { configured: true }) },
  })
  render(<AiProvidersSettings />)
  await userEvent.type(await screen.findByLabelText('Anthropic API key'), 'sk-secret')
  await userEvent.click(screen.getAllByRole('button', { name: 'Save' })[1])
  expect(await screen.findByText('Saved.')).toBeInTheDocument()
  const put = fetchMock.mock.calls.find(([, i]) => i?.method === 'PUT')!
  expect(JSON.parse(String(put[1]?.body))).toEqual({ api_key: 'sk-secret' })
  expect(screen.getByLabelText('Anthropic API key')).toHaveValue('')
  expect(screen.queryByText(/sk-secret/)).not.toBeInTheDocument()
  expect(screen.getAllByText('configured').length).toBeGreaterThan(1)
})

test('shows an error alert when the key is rejected', async () => {
  mockApi({
    '/api/ai/providers': { body: list() },
    'PUT /api/ai/providers/anthropic/credentials': {
      status: 400,
      body: { detail: 'Anthropic did not accept the API key.' },
    },
  })
  render(<AiProvidersSettings />)
  await userEvent.type(await screen.findByLabelText('Anthropic API key'), 'bad')
  await userEvent.click(screen.getAllByRole('button', { name: 'Save' })[1])
  expect(await screen.findByRole('alert')).toHaveTextContent('did not accept the API key')
})

test('verifies and removes a configured key', async () => {
  const fetchMock = mockApi({
    '/api/ai/providers': { body: list({ configured: true }) },
    '/api/ai/providers/anthropic/check': { body: { ok: true } },
    'DELETE /api/ai/providers/anthropic/credentials': { body: provider('anthropic', 'Anthropic') },
  })
  render(<AiProvidersSettings />)
  await screen.findByLabelText('Anthropic API key')
  const verify = screen.getAllByRole('button', { name: 'Verify' })[0]
  await userEvent.click(verify)
  expect(await screen.findByText('The key works.')).toBeInTheDocument()
  await userEvent.click(screen.getAllByRole('button', { name: 'Remove key' })[0])
  expect(await screen.findByText('Saved key removed.')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledWith('/api/ai/providers/anthropic/credentials', { method: 'DELETE' })
})

test('changes the default provider', async () => {
  const fetchMock = mockApi({
    '/api/ai/providers': { body: list() },
    'PUT /api/ai/default': { body: {} },
  })
  render(<AiProvidersSettings />)
  await userEvent.click(await screen.findByRole('combobox', { name: 'Default provider' }))
  await userEvent.click(within(screen.getByRole('listbox')).getByText('Google Gemini'))
  const put = fetchMock.mock.calls.find(([u]) => u === '/api/ai/default')!
  expect(JSON.parse(String(put[1]?.body))).toEqual({ provider: 'gemini' })
})
