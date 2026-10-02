// @vitest-environment happy-dom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { Faq } from './Faq'

afterEach(() => {
  cleanup()
  delete (window as Window & { dataLayer?: unknown }).dataLayer
})

describe('Faq', () => {
  it('records the question and whether it opened', () => {
    const win = window as Window & { dataLayer?: Record<string, unknown>[] }
    win.dataLayer = []
    render(<Faq items={[{ q: 'Where?', a: 'Hong Kong.' }]} />)
    const details = screen.getByText('Where?').closest('details')
    expect(details).toBeTruthy()
    if (!details) return
    details.open = true
    fireEvent(details, new Event('toggle', { bubbles: true }))
    expect(win.dataLayer[0]).toMatchObject({
      event: 'faq_toggle',
      question: 'Where?',
      state: 'open',
    })
  })
})
