import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, test, vi } from 'vitest'
import { mockApi } from '../../test-utils'
import SkillsSettings from './SkillsSettings'

afterEach(() => vi.unstubAllGlobals())

const skill = (step: string, over: Record<string, unknown> = {}) => ({
  step,
  content: `default ${step}`,
  default_content: `default ${step}`,
  customized: false,
  ...over,
})
const open = (name: string) => userEvent.click(screen.getByRole('button', { name: new RegExp(`^${name}`) }))
const all = [skill('planner'), skill('implementer'), skill('reviewer')]

test('shows an editor per step with its Default/Customised state', async () => {
  mockApi({
    '/api/skills': { body: [skill('planner', { content: 'mine', customized: true }), ...all.slice(1)] },
  })
  render(<SkillsSettings />)
  await screen.findByText('Customised')
  // collapsed by default
  expect(screen.queryByRole('region')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: /^Plan generation/ })).toHaveAttribute('aria-expanded', 'false')
  await open('Plan generation')
  await open('Implementation')
  await open('Code review')
  expect(screen.getByLabelText('Plan generation skill')).toHaveValue('mine')
  expect(screen.getByLabelText('Implementation skill')).toHaveValue('default implementer')
  expect(screen.getByLabelText('Code review skill')).toHaveValue('default reviewer')
  expect(screen.getByText('Customised')).toBeInTheDocument()
  expect(screen.getAllByText('Default')).toHaveLength(2)
})

test('saving an edit marks the skill customised', async () => {
  const fetchMock = mockApi({
    '/api/skills': { body: all },
    'PUT /api/skills/reviewer': { body: skill('reviewer', { content: 'new', customized: true }) },
  })
  render(<SkillsSettings />)
  await screen.findByText('Code review')
  await open('Code review')
  const box = screen.getByLabelText('Code review skill')
  const save = screen.getByRole('button', { name: 'Save' })
  expect(save).toBeDisabled()
  await userEvent.clear(box)
  await userEvent.type(box, 'new')
  await userEvent.click(save)
  expect(await screen.findByText('Saved.')).toBeInTheDocument()
  expect(screen.getByText('Customised')).toBeInTheDocument()
  const put = fetchMock.mock.calls.find(([, i]) => i?.method === 'PUT')!
  expect(JSON.parse(put[1]!.body as string)).toEqual({ content: 'new' })
})

test('reset to default restores the built-in text', async () => {
  mockApi({
    '/api/skills': { body: [skill('planner', { content: 'mine', customized: true }), ...all.slice(1)] },
    'DELETE /api/skills/planner': { body: skill('planner') },
  })
  render(<SkillsSettings />)
  await screen.findByText('Customised')
  await open('Plan generation')
  await userEvent.click(screen.getByRole('button', { name: 'Reset to default' }))
  expect(await screen.findByDisplayValue('default planner')).toBeInTheDocument()
  expect(screen.queryByText('Customised')).not.toBeInTheDocument()
})

test('shows the server validation error', async () => {
  mockApi({
    '/api/skills': { body: all },
    'PUT /api/skills/planner': { status: 422, body: { detail: 'needs Mode sections' } },
  })
  render(<SkillsSettings />)
  await screen.findByText('Plan generation')
  await open('Plan generation')
  await userEvent.type(screen.getByLabelText('Plan generation skill'), 'x')
  await userEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('needs Mode sections')
})
