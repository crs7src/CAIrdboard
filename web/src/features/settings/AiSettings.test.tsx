import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { card, mockApi } from '../../test-utils'
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
    auto_review: true,
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

test('project key suggests only projects with cards, excluding ones already used', async () => {
  mockApi({
    '/api/ai-config': { body: config },
    '/api/cards': { body: [card('AB-1'), card('XY-1'), card('XY-2'), card('ZZ-1')] },
  })
  render(<AiSettings />)
  await screen.findByLabelText('Eligible Jira statuses')
  await userEvent.click(screen.getByRole('button', { name: 'Add project' }))
  await userEvent.click(screen.getByLabelText('Project key 2'))
  const options = (await screen.findAllByRole('option')).map((o) => o.textContent)
  expect(options).toEqual(['XY', 'ZZ'])
  await userEvent.click(screen.getByRole('option', { name: 'ZZ' }))
  expect(screen.getByLabelText('Project key 2')).toHaveValue('ZZ')
})

test('project key still accepts free text when cards cannot be loaded', async () => {
  mockApi({
    '/api/ai-config': { body: config },
    '/api/cards': { status: 503, body: { detail: 'Jira is not configured' } },
  })
  render(<AiSettings />)
  await screen.findByLabelText('Eligible Jira statuses')
  await userEvent.type(screen.getByLabelText('Project key 1'), 'q')
  expect(screen.getByLabelText('Project key 1')).toHaveValue('ABQ')
  expect(screen.queryByRole('alert')).toBeNull()
})

test('browse picks a repo folder by navigating the server file tree', async () => {
  mockApi({
    '/api/ai-config': { body: config },
    '/api/fs/dirs?path=%2Frepos%2Fab': { body: { path: '/repos/ab', parent: '/repos', dirs: [] } },
    '/api/fs/dirs?path=%2Frepos': {
      body: { path: '/repos', parent: '/', dirs: [{ name: 'ab', is_git: true }, { name: 'docs', is_git: false }] },
    },
  })
  render(<AiSettings />)
  await screen.findByLabelText('Eligible Jira statuses')
  await userEvent.click(screen.getByRole('button', { name: 'Browse for repo 1' }))
  expect(await screen.findByText('Choose a repository folder')).toBeVisible()
  await userEvent.click(await screen.findByText('Up'))
  await userEvent.click(await screen.findByText('docs'))
  // docs listing is not mocked, so navigation reports an error and stays put
  expect(await screen.findByRole('alert')).toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: 'Select this folder' }))
  expect(screen.getByLabelText('Repo path 1')).toHaveValue('/repos')
})

test('auto review switch is on by default and reflects a loaded false', async () => {
  mockApi({ '/api/ai-config': { body: config } })
  const { unmount } = render(<AiSettings />)
  const label = 'Automatically start the review when implementation completes'
  expect(await screen.findByRole('switch', { name: label })).toBeChecked()
  unmount()
  mockApi({ '/api/ai-config': { body: { ...config, auto_review: false } } })
  render(<AiSettings />)
  expect(await screen.findByRole('switch', { name: label })).not.toBeChecked()
})

test('toggling auto review sends it in the save payload', async () => {
  const fetchMock = mockApi({
    '/api/ai-config': { body: config },
    'PUT /api/ai-config': (init) => ({ body: JSON.parse(init!.body as string) }),
  })
  render(<AiSettings />)
  await userEvent.click(
    await screen.findByRole('switch', {
      name: 'Automatically start the review when implementation completes',
    }),
  )
  await userEvent.click(screen.getByRole('button', { name: 'Save AI settings' }))
  await screen.findByRole('status')
  const put = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')!
  expect(JSON.parse(put[1]!.body as string).auto_review).toBe(false)
})
