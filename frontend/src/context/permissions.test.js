import { describe, expect, it } from 'vitest'
import { can } from './permissions.js'

describe('can(role, action)', () => {
  it('allows administrators every action', () => {
    expect(can('admin', 'manage_cameras')).toBe(true)
    expect(can('admin', 'delete_user')).toBe(true)
    expect(can('admin', 'review')).toBe(true)
  })

  it('allows reviewers to view, review and export only', () => {
    expect(can('reviewer', 'view')).toBe(true)
    expect(can('reviewer', 'review')).toBe(true)
    expect(can('reviewer', 'export')).toBe(true)
    expect(can('reviewer', 'manage_cameras')).toBe(false)
  })

  it('keeps viewers read-only and rejects unknown roles', () => {
    expect(can('viewer', 'view')).toBe(true)
    expect(can('viewer', 'review')).toBe(false)
    expect(can('viewer', 'export')).toBe(false)
    expect(can('unknown', 'view')).toBe(false)
  })
})
