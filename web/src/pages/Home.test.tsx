import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import Home from './Home'

test('shows the project title and summary', () => {
  render(<Home />)
  expect(screen.getByRole('heading', { level: 1, name: 'AI Card Board' })).toBeInTheDocument()
  expect(screen.getByText(/Review the Jira cards assigned to you/)).toBeInTheDocument()
})
