import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const { useAuthMock, toastMock, getViolationMock } = vi.hoisted(() => ({
  useAuthMock: vi.fn(() => ({ user: { role: 'viewer' } })),
  toastMock: vi.fn(),
  getViolationMock: vi.fn(async (id) => ({ event_id: id, camera_id: 'cam-1', track_id: 7, violation_type: 'helmet', ai_result: 'NO_HELMET', detection_confidence: 0.9, evidence: {}, review_status: 'UNREVIEWED', created_at: '2026-11-09T12:00:00Z' })),
}))

vi.mock('../context/AuthContext.jsx', () => ({ useAuth: useAuthMock }))
vi.mock('../context/ToastContext.jsx', () => ({ useToast: () => toastMock }))
vi.mock('../api/index.js', () => ({ getViolation: getViolationMock, reviewViolation: vi.fn() }))

import ViolationDetailDrawer from './ViolationDetailDrawer.jsx'

describe('viewer permissions in violation details', () => {
  it('does not show the review controls to a viewer', async () => {
    render(<ViolationDetailDrawer selected={{ event_id: 'evt-7', review_history: [] }} onClose={vi.fn()} onReviewed={vi.fn()} />)
    expect(await screen.findByText('Original AI result')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Confirm violation' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reject' })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Reviewer note')).not.toBeInTheDocument()
  })
})
