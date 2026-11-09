import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { useAuthMock, toastMock, useAlertsSocketMock, liveState } = vi.hoisted(() => ({
  useAuthMock: vi.fn(),
  toastMock: vi.fn(),
  useAlertsSocketMock: vi.fn(),
  liveState: { alerts: [], connected: false },
}))

vi.mock('./AuthContext.jsx', () => ({ useAuth: useAuthMock }))
vi.mock('./ToastContext.jsx', () => ({ useToast: () => toastMock }))
vi.mock('../hooks/useAlertsSocket.js', () => ({
  useAlertsSocket: (token, onAlert) => {
    useAlertsSocketMock(token)
    liveState.onAlert = onAlert
    return liveState
  },
}))

import { LiveAlertsProvider, useLiveAlerts } from './LiveAlertsContext.jsx'

describe('LiveAlertsContext', () => {
  beforeEach(() => {
    useAuthMock.mockReturnValue({ user: { id: 'u1', role: 'admin' } })
    toastMock.mockReset()
    useAlertsSocketMock.mockClear()
    liveState.alerts = []
    liveState.connected = true
    liveState.onAlert = null
    window.sessionStorage.setItem('traffic_access_token', 'context-token')
  })

  afterEach(() => window.sessionStorage.clear())

  const wrapper = ({ children }) => <LiveAlertsProvider>{children}</LiveAlertsProvider>

  it('provides the current alerts and connection state to consumers', () => {
    liveState.alerts = [{ event_id: 'evt-1' }]
    const { result } = renderHook(() => useLiveAlerts(), { wrapper })
    expect(result.current).toMatchObject({ alerts: [{ event_id: 'evt-1' }], connected: true })
  })

  it('shows an error toast for a new violation alert', () => {
    renderHook(() => useLiveAlerts(), { wrapper })
    act(() => liveState.onAlert({ violation_type: 'helmet', provisional: false }))
    expect(toastMock).toHaveBeenCalledWith('New alert: helmet', 'error')
  })

  it('shows an informational toast for a candidate alert', () => {
    renderHook(() => useLiveAlerts(), { wrapper })
    act(() => liveState.onAlert({ violation_type: 'seatbelt', provisional: true }))
    expect(toastMock).toHaveBeenCalledWith('New candidate: seatbelt', 'info')
  })

  it('passes an authenticated user token to the socket hook', () => {
    renderHook(() => useLiveAlerts(), { wrapper })
    expect(useAlertsSocketMock).toHaveBeenCalledWith('context-token')
  })

  it('does not connect the socket before authentication', () => {
    useAuthMock.mockReturnValue({ user: null })
    liveState.connected = false
    const { result } = renderHook(() => useLiveAlerts(), { wrapper })
    expect(useAlertsSocketMock).toHaveBeenCalledWith(null)
    expect(result.current.connected).toBe(false)
  })

  it('throws a clear error when used outside its provider', () => {
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    expect(() => renderHook(() => useLiveAlerts())).toThrow('useLiveAlerts must be used inside LiveAlertsProvider')
    consoleError.mockRestore()
  })
})
