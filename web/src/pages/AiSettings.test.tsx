import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { mockApi } from '../test-utils'
import AiSettings from './AiSettings'

afterEach(() => vi.unstubAllGlobals())

const config = {
  eligible_statuses: ['Backlog', 'To Do'],
  project_repos: { AB: '/repos/ab' },
}

test('loads statuses and repo mappings', async () => {
  mockApi({ '/api/ai-config': { body: config } })
  render(<AiSettings />)
  expect(await screen.findByLabelText('Eligible Jira statuses')).toHaveValue('Backlog, To Do')
  expect(screen.getByLabelText('Project key 1')).toHaveValue('AB')
  expect(screen.getByLabelText('Repo path 1')).toHaveValue('/repos/ab')
})

test('saves edited statuses and added/removed projects', async () => {
  const fetchMock = mockApi({
    '/api/ai-config': { body: config },
    'PUT /api/ai-config': (init) => ({ body: JSON.parse(init!.body as string) }),
  })
  render(<AiSettings />)
  const statuses = await screen.findByLabelText('Eligible Jira statuses')
  await userEvent.clear(statuses)
  await userEvent.type(statuses, 'Backlog,  Ready to Play ,')
  await userEvent.click(screen.getByRole('button', { name: 'Add project' }))
  await userEvent.type(screen.getByLabelText('Project key 2'), 'XY')
  await userEvent.type(screen.getByLabelText('Repo path 2'), '/repos/xy')
  await userEvent.click(screen.getByRole('button', { name: 'Remove project 1' }))
  await userEvent.click(screen.getByRole('button', { name: 'Save AI settings' }))

  expect(await screen.findByRole('status')).toHaveTextContent('AI settings saved.')
  const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')!
  expect(JSON.parse(put[1]!.body as string)).toEqual({
    eligible_statuses: ['Backlog', 'Ready to Play'],
    project_repos: { XY: '/repos/xy' },
  })
})

test('ignores completely empty project rows', async () => {
  const fetchMock = mockApi({
    '/api/ai-config': { body: { ...config, project_repos: {} } },
    'PUT /api/ai-config': (init) => ({ body: JSON.parse(init!.body as string) }),
  })
  render(<AiSettings />)
  await screen.findByLabelText('Eligible Jira statuses')
  await userEvent.click(screen.getByRole('button', { name: 'Add project' }))
  await userEvent.click(screen.getByRole('button', { name: 'Save AI settings' }))
  await screen.findByRole('status')
  const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')!
  expect(JSON.parse(put[1]!.body as string).project_repos).toEqual({})
})

test('shows validation errors from the server', async () => {
  mockApi({
    '/api/ai-config': { body: config },
    'PUT /api/ai-config': { status: 422, body: { detail: [{ msg: 'Value error, must be absolute' }] } },
  })
  render(<AiSettings />)
  await screen.findByLabelText('Eligible Jira statuses')
  await userEvent.type(screen.getByLabelText('Repo path 1'), 'x')
  await userEvent.click(screen.getByRole('button', { name: 'Save AI settings' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('must be absolute')
})
