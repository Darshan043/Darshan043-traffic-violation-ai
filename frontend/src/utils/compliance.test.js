import { describe, expect, it } from 'vitest'
import { calculateCompliance } from './compliance.js'

describe('calculateCompliance', () => {
  it('uses compliant / (compliant + violations) as a percentage', () => {
    expect(calculateCompliance(75, 25)).toBe(75)
  })

  it('excludes needs-review values from the calculation', () => {
    expect(calculateCompliance(3, 1)).toBe(75)
  })

  it('returns zero when there are no decided events', () => {
    expect(calculateCompliance(0, 0)).toBe(0)
  })
})
