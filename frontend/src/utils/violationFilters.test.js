import { describe, expect, it } from 'vitest'
import { readViolationFilters, updateViolationFilter } from './violationFilters.js'

describe('violation filter URL state', () => {
  it('round-trips supported filters through query parameters', () => {
    let params = new URLSearchParams()
    for (const [key, value] of Object.entries({ type: 'helmet', result: 'needs_review', camera: 'cam-2', date_from: '2026-11-01', date_to: '2026-11-09', review_status: 'UNREVIEWED', track_id: '42', page: '3', event_id: 'evt-4' })) {
      params = updateViolationFilter(params, key, value, false)
    }
    expect(readViolationFilters(params.toString())).toEqual({ type: 'helmet', result: 'needs_review', camera: 'cam-2', date_from: '2026-11-01', date_to: '2026-11-09', review_status: 'UNREVIEWED', track_id: '42', page: '3', event_id: 'evt-4' })
  })

  it('clears a filter and resets pagination when another filter changes', () => {
    const updated = updateViolationFilter(new URLSearchParams('type=helmet&page=4'), 'type', '')
    expect(updated.has('type')).toBe(false)
    expect(updated.has('page')).toBe(false)
  })
})
