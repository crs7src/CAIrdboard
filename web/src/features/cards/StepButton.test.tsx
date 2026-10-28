import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import StepButton from './StepButton'

test('failed renders an error button that retries on click', async () => {
  const onRun = vi.fn()
  render(<StepButton label="Review" status="failed" onRun={onRun} />)
  const button = screen.getByRole('button', { name: 'Review failed' })
  expect(button).toBeEnabled()
  expect(button.querySelector('[data-testid="ErrorIcon"]')).not.toBeNull()
  await userEvent.click(button)
  expect(onRun).toHaveBeenCalledTimes(1)
})

test('a done step with an href is a link that opens in a new tab', () => {
  render(<StepButton label="Create MR" status="done" href="https://x/mr/1" />)
  const link = screen.getByRole('link', { name: 'Create MR' })
  expect(link).toHaveAttribute('href', 'https://x/mr/1')
  expect(link).toHaveAttribute('target', '_blank')
  expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
})

test('a done step without an href stays a plain check', () => {
  render(<StepButton label="Create MR" status="done" />)
  expect(screen.getByRole('img', { name: 'Create MR' })).toBeInTheDocument()
  expect(screen.queryByRole('link')).not.toBeInTheDocument()
})
