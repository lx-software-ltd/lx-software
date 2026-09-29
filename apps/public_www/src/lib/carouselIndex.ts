/** Index of the snapped card, including the case where the last card cannot reach the left edge. */
export function carouselIndex(scrollLeft: number, maxScroll: number, offsets: number[]): number {
  if (offsets.length === 0) return 0
  if (maxScroll > 0 && scrollLeft >= maxScroll - 1) return offsets.length - 1
  let closest = 0
  let distance = Number.POSITIVE_INFINITY
  offsets.forEach((offset, position) => {
    const delta = Math.abs(offset - scrollLeft)
    if (delta < distance) {
      distance = delta
      closest = position
    }
  })
  return closest
}
