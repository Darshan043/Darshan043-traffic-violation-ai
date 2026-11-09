import { describe, expect, it } from 'vitest'
import { normalizedToPixels, pixelsToNormalized } from './zoneCoordinates.js'

describe('zone coordinate conversion', () => {
  it('converts normalized points to displayed image pixels', () => {
    expect(normalizedToPixels([[0.25, 0.5], [1, 0]], 800, 400)).toEqual([[200, 200], [800, 0]])
  })

  it('round-trips pixel points through normalized coordinates', () => {
    const normalized = [[0.125, 0.75], [0.9, 0.2]]
    const pixels = normalizedToPixels(normalized, 960, 540)
    expect(pixelsToNormalized(pixels, 960, 540)).toEqual(normalized)
  })

  it('clamps clicked pixels to the image bounds', () => {
    expect(pixelsToNormalized([[-2, 500], [500, 200]], 400, 400)).toEqual([[0, 1], [1, 0.5]])
  })
})
