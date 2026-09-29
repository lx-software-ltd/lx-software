import { describe, expect, it } from 'vitest'
import { carouselIndex } from './carouselIndex'

describe('carouselIndex', () => {
  const offsets = [0, 340, 680, 1020, 1360, 1700]

  it('returns 0 when there are no cards', () => {
    expect(carouselIndex(0, 0, [])).toBe(0)
  })

  it('picks the nearest card', () => {
    expect(carouselIndex(350, 1700, offsets)).toBe(1)
    expect(carouselIndex(0, 1700, offsets)).toBe(0)
  })

  it('treats the scroll end as the last card', () => {
    expect(carouselIndex(1699, 1700, offsets)).toBe(5)
    expect(carouselIndex(1700, 1700, offsets)).toBe(5)
  })

  it('does not clamp when the track cannot scroll', () => {
    expect(carouselIndex(0, 0, offsets)).toBe(0)
  })
})
