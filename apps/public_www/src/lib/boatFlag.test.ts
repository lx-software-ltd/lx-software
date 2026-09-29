import { describe, expect, it } from 'vitest'
import { BOAT_FLAG, BOAT_FLAG_X, boatFlagAtTime } from './boatFlag'

describe('boat flag track', () => {
  it('follows the junk from left to right and is absent when the boat is gone', () => {
    expect(BOAT_FLAG_X).toHaveLength(441)
    expect(boatFlagAtTime(0)).toBeNull()
    expect(boatFlagAtTime(18)).toBeNull()
    expect(boatFlagAtTime(Number.NaN)).toBeNull()

    const early = boatFlagAtTime(4)
    const mid = boatFlagAtTime(7.5)
    const late = boatFlagAtTime(12)
    expect(early).not.toBeNull()
    expect(mid).not.toBeNull()
    expect(late).not.toBeNull()
    expect(mid).toMatchObject({ x: 544, y: 171, width: 36, height: 20 })
    expect(early!.x).toBeLessThan(mid!.x)
    expect(mid!.x).toBeLessThan(late!.x)

    for (let i = 1; i < BOAT_FLAG_X.length; i += 1) {
      expect(BOAT_FLAG_X[i]).toBeGreaterThanOrEqual(BOAT_FLAG_X[i - 1])
    }
    expect(BOAT_FLAG.videoWidth).toBe(1280)
    expect(BOAT_FLAG.fps).toBe(24)
  })
})
