import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { mockApi } from '../../test-utils'
import MergeRequest, { MR_POLL_MS } from './MergeRequest'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const mr = (over: Record<string, unknown> = {}) => ({
  card_key: 'AB-1',
  version: 1,
  state: 'created',
  branch: 'AB-1_add_dark_mode',
  target_branch: 'main',
  title: 'AB-1 add dark mode',
  provider: 'gitlab',
  host_project: 'grp/app',
  mr_iid: 42,
  mr_url: 'https://git.x.com/grp/app/-/merge_requests/42',
  updated_existing: false,
  outdated: false,
  error: null,
  ...over,
})
const NONE = { status: 404, body: { detail: 'none' } }

test('is hidden until the test is approved or a merge request exists', async () => {
  mockApi({ '/api/cards/AB-1/merge-request': NONE })
  const { container } = render(<MergeRequest cardKey="AB-1" approved={false} />)
  await vi.waitFor(() => expect(fetch).toHaveBeenCalled())
  expect(container).toBeEmptyDOMElement()
})

test('creating polls until the merge request link appears', async () => {
  const fetchMock = mockApi({
    '/api/cards/AB-1/merge-request': [NONE, { body: mr({ state: 'running', mr_url: null, mr_iid: null }) }, { body: mr() }],
    'POST /api/cards/AB-1/merge-request': { status: 202, body: mr({ state: 'running', mr_url: null, mr_iid: null }) },
  })
  vi.useFakeTimers({ shouldAdvanceTime: true })
  render(<MergeRequest cardKey="AB-1" approved />)
  await userEvent.click(await screen.findByRole('button', { name: 'Create merge request' }))
  expect(fetchMock).toHaveBeenCalledWith('/api/cards/AB-1/merge-request', { method: 'POST' })
  expect(await screen.findByText(/Pushing the branch/)).toBeInTheDocument()
  await vi.advanceTimersByTimeAsync(MR_POLL_MS)
  await vi.advanceTimersByTimeAsync(MR_POLL_MS)
  const link = await screen.findByRole('link', { name: '!42 AB-1 add dark mode' })
  expect(link).toHaveAttribute('href', 'https://git.x.com/grp/app/-/merge_requests/42')
  expect(link).toHaveAttribute('target', '_blank')
  expect(screen.queryByRole('button', { name: /Create merge request|Push updates/ })).not.toBeInTheDocument()
})

test('new commits offer Push updates, but only while approved', async () => {
  mockApi({ '/api/cards/AB-1/merge-request': { body: mr({ outdated: true }) } })
  const { rerender } = render(<MergeRequest cardKey="AB-1" approved={false} />)
  expect(await screen.findByRole('button', { name: 'Push updates' })).toBeDisabled()
  expect(screen.getByText(/Approve the manual test again/)).toBeInTheDocument()
  rerender(<MergeRequest cardKey="AB-1" approved />)
  expect(await screen.findByRole('button', { name: 'Push updates' })).toBeEnabled()
})

test('a failure shows the error and can be retried', async () => {
  mockApi({
    '/api/cards/AB-1/merge-request': { body: mr({ state: 'failed', mr_url: null, mr_iid: null, error: 'git push failed' }) },
  })
  render(<MergeRequest cardKey="AB-1" approved />)
  expect(await screen.findByText('git push failed')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Create merge request' })).toBeEnabled()
})

test('a refused start shows the server message', async () => {
  mockApi({
    '/api/cards/AB-1/merge-request': NONE,
    'POST /api/cards/AB-1/merge-request': { status: 409, body: { detail: 'No GitLab project is known' } },
  })
  render(<MergeRequest cardKey="AB-1" approved />)
  await userEvent.click(await screen.findByRole('button', { name: 'Create merge request' }))
  expect(await screen.findByText('No GitLab project is known')).toBeInTheDocument()
})

test('uses pull request wording for a GitHub project', async () => {
  mockApi({
    '/api/cards/AB-1/merge-request': { body: mr({ provider: 'github', outdated: true, mr_iid: 7, mr_url: 'https://github.com/o/r/pull/7' }) },
  })
  render(<MergeRequest cardKey="AB-1" approved />)
  expect(await screen.findByRole('link', { name: /#7 AB-1 add dark mode/ })).toBeInTheDocument()
  expect(screen.getByText(/Push the updates to the pull request/)).toBeInTheDocument()
})

test('before any run the wording follows the project host', async () => {
  mockApi({
    '/api/cards/AB-1/merge-request': NONE,
    '/api/repo-hosts/AB': { body: { project: 'AB', repo: '/r', provider: 'github', path: 'o/r', source: 'origin', detected: null } },
  })
  render(<MergeRequest cardKey="AB-1" approved />)
  expect(await screen.findByRole('button', { name: 'Create pull request' })).toBeInTheDocument()
})

const DEFAULTS = { title: 'AB-1 add dark mode', description: '[AB-1](https://x/AB-1):' }
const RUNNING = { status: 202, body: mr({ state: 'running', mr_url: null, mr_iid: null }) }

test('the title and description are prefilled from the defaults and sent when edited', async () => {
  const fetchMock = mockApi({
    '/api/cards/AB-1/merge-request': NONE,
    '/api/cards/AB-1/merge-request/defaults': { body: DEFAULTS },
    'POST /api/cards/AB-1/merge-request': RUNNING,
  })
  render(<MergeRequest cardKey="AB-1" approved />)
  const title = await screen.findByRole('textbox', { name: 'Title' })
  expect(title).toHaveValue(DEFAULTS.title)
  expect(screen.getByRole('textbox', { name: 'Description' })).toHaveValue(DEFAULTS.description)
  await userEvent.clear(title)
  await userEvent.type(title, 'My title')
  await userEvent.click(screen.getByRole('button', { name: 'Create merge request' }))
  expect(fetchMock).toHaveBeenCalledWith('/api/cards/AB-1/merge-request', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: 'My title', description: DEFAULTS.description }),
  })
  expect(await screen.findByRole('textbox', { name: 'Title' })).toBeDisabled()
  expect(screen.getByRole('textbox', { name: 'Description' })).toBeDisabled()
})

test('an empty title disables the button', async () => {
  mockApi({
    '/api/cards/AB-1/merge-request': NONE,
    '/api/cards/AB-1/merge-request/defaults': { body: DEFAULTS },
  })
  render(<MergeRequest cardKey="AB-1" approved />)
  await userEvent.clear(await screen.findByRole('textbox', { name: 'Title' }))
  expect(screen.getByRole('button', { name: 'Create merge request' })).toBeDisabled()
})

test('no fields are offered once the merge request exists', async () => {
  mockApi({ '/api/cards/AB-1/merge-request': { body: mr({ outdated: true }) } })
  render(<MergeRequest cardKey="AB-1" approved />)
  await screen.findByRole('button', { name: 'Push updates' })
  expect(screen.queryByRole('textbox', { name: 'Title' })).not.toBeInTheDocument()
  expect(screen.getByText(/does not change the title or description/)).toBeInTheDocument()
})
