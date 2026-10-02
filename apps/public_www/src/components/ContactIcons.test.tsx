// @vitest-environment happy-dom
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { ContactIcons } from './ContactIcons'

afterEach(() => {
  cleanup()
})

describe('ContactIcons', () => {
  it('shows Not configured when a channel has no link', () => {
    render(
      <MemoryRouter>
        <ContactIcons />
      </MemoryRouter>,
    )
    expect(screen.getAllByText('Not configured')).toHaveLength(3)
    expect(screen.getByRole('link', { name: 'Email hello@lx-software.com' })).toBeTruthy()
  })
})
