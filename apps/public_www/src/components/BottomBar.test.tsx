// @vitest-environment happy-dom
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { BottomBar } from './BottomBar'

afterEach(() => {
  cleanup()
})

describe('BottomBar', () => {
  it('names LX Software as a Hong Kong sole proprietorship', () => {
    render(
      <MemoryRouter>
        <BottomBar />
      </MemoryRouter>,
    )
    expect(
      screen.getByText(/LX Software \(a sole proprietorship registered in Hong Kong\)/),
    ).toBeTruthy()
    expect(screen.queryByText(/LX Software Limited/)).toBeNull()
  })
})
