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
