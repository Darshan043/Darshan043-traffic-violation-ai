import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { getTokenMock, apiUrlMock, isMockModeMock, connectMockAlertsMock } = vi.hoisted(() => ({
  getTokenMock: vi.fn(),
  apiUrlMock: vi.fn(() => 'http://localhost:8000/ws/alerts'),
  isMockModeMock: vi.fn(() => false),
  connectMockAlertsMock: vi.fn(),
}))

vi.mock('../api/client.js', () => ({ getToken: getTokenMock, apiUrl: apiUrlMock }))
vi.mock('../api/index.js', () => ({ isMockMode: isMockModeMock, connectMockAlerts: connectMockAlertsMock }))

import { useAlertsSocket } from './useAlertsSocket.js'

class FakeWebSocket {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSING = 2
  static CLOSED = 3
  static instances = []

  constructor(url) {
    this.url = String(url)
    this.readyState = FakeWebSocket.CONNECTING
    this.close = vi.fn(() => {
      this.readyState = FakeWebSocket.CLOSED
      this.onclose?.()
    })
    FakeWebSocket.instances.push(this)
  }
}

const emit = (socket, message) => socket.onmessage?.({ data: typeof message === 'string' ? message : JSON.stringify(message) })
const violation = (eventId) => ({ type: 'violation', event: { event_id: eventId, camera_id: 'cam-1', violation_type: 'helmet', ai_result: 'NO_HELMET' } })

describe('useAlertsSocket', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.stubGlobal('WebSocket', FakeWebSocket)
    FakeWebSocket.instances = []
    getTokenMock.mockReturnValue('valid-token')
    isMockModeMock.mockReturnValue(false)
    connectMockAlertsMock.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('connects with the token in the WebSocket query string', () => {
    renderHook(() => useAlertsSocket())
    expect(FakeWebSocket.instances).toHaveLength(1)
    expect(FakeWebSocket.instances[0].url).toContain('ws://localhost:8000/ws/alerts?token=valid-token')
  })

  it('does not connect without a token', () => {
    getTokenMock.mockReturnValue(null)
    const { result } = renderHook(() => useAlertsSocket())
    expect(FakeWebSocket.instances).toHaveLength(0)
    expect(result.current.connected).toBe(false)
  })

  it('accepts incoming violation messages', () => {
    const { result } = renderHook(() => useAlertsSocket())
    act(() => emit(FakeWebSocket.instances[0], violation('evt-1')))
    expect(result.current.alerts[0]).toMatchObject({ event_id: 'evt-1', violation_type: 'helmet', provisional: false })
  })

  it('normalizes candidate alerts and candidate confidence', () => {
    const { result } = renderHook(() => useAlertsSocket())
    act(() => emit(FakeWebSocket.instances[0], { type: 'event_candidate', provisional: true, event: { event_id: 'candidate-1', confidence: 0.7, decision: 'unclear' } }))
    expect(result.current.alerts[0]).toMatchObject({ event_id: 'candidate-1', detection_confidence: 0.7, ai_result: 'unclear', provisional: true })
    expect(result.current.alerts[0].created_at).toBeTruthy()
  })

  it('ignores invalid JSON and unsupported message shapes', () => {
    const { result } = renderHook(() => useAlertsSocket())
    act(() => {
      emit(FakeWebSocket.instances[0], '{broken')
      emit(FakeWebSocket.instances[0], { type: 'finished', camera_id: 'cam-1' })
      emit(FakeWebSocket.instances[0], { type: 'violation' })
    })
    expect(result.current.alerts).toEqual([])
  })

  it('replaces duplicate event IDs without adding another row', () => {
    const { result } = renderHook(() => useAlertsSocket())
    act(() => {
      emit(FakeWebSocket.instances[0], violation('evt-1'))
      emit(FakeWebSocket.instances[0], { ...violation('evt-1'), event: { ...violation('evt-1').event, violation_type: 'seatbelt' } })
    })
    expect(result.current.alerts).toHaveLength(1)
    expect(result.current.alerts[0].violation_type).toBe('seatbelt')
  })

  it('keeps at most 50 alerts', () => {
    const { result } = renderHook(() => useAlertsSocket())
    act(() => { for (let index = 0; index < 55; index += 1) emit(FakeWebSocket.instances[0], violation(`evt-${index}`)) })
    expect(result.current.alerts).toHaveLength(50)
    expect(result.current.alerts[0].event_id).toBe('evt-54')
  })

  it('updates connection status on open and close', () => {
    const { result } = renderHook(() => useAlertsSocket())
    const socket = FakeWebSocket.instances[0]
    act(() => { socket.readyState = FakeWebSocket.OPEN; socket.onopen() })
    expect(result.current.connected).toBe(true)
    act(() => socket.onclose())
    expect(result.current.connected).toBe(false)
  })

  it('reconnects after disconnection using an increasing delay', async () => {
    renderHook(() => useAlertsSocket())
    act(() => FakeWebSocket.instances[0].onclose())
    await act(async () => { await vi.advanceTimersByTimeAsync(999) })
    expect(FakeWebSocket.instances).toHaveLength(1)
    await act(async () => { await vi.advanceTimersByTimeAsync(1) })
    expect(FakeWebSocket.instances).toHaveLength(2)
    act(() => FakeWebSocket.instances[1].onclose())
    await act(async () => { await vi.advanceTimersByTimeAsync(1999) })
    expect(FakeWebSocket.instances).toHaveLength(2)
    await act(async () => { await vi.advanceTimersByTimeAsync(1) })
    expect(FakeWebSocket.instances).toHaveLength(3)
  })

  it('caps the exponential reconnect delay at 30 seconds', async () => {
    renderHook(() => useAlertsSocket())
    for (const delay of [1000, 2000, 4000, 8000, 16000, 30000]) {
      act(() => FakeWebSocket.instances.at(-1).onclose())
      await act(async () => { await vi.advanceTimersByTimeAsync(delay) })
    }
    act(() => FakeWebSocket.instances.at(-1).onclose())
    await act(async () => { await vi.advanceTimersByTimeAsync(29999) })
    expect(FakeWebSocket.instances).toHaveLength(7)
    await act(async () => { await vi.advanceTimersByTimeAsync(1) })
    expect(FakeWebSocket.instances).toHaveLength(8)
  })

  it('closes the socket and cancels reconnect work on unmount', () => {
    const { unmount } = renderHook(() => useAlertsSocket())
    const socket = FakeWebSocket.instances[0]
    unmount()
    expect(socket.close).toHaveBeenCalledTimes(1)
    expect(vi.getTimerCount()).toBe(0)
  })
})
