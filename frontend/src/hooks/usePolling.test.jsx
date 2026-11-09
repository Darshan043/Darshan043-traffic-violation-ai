import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { usePolling } from './usePolling.js'

describe('usePolling', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    Object.defineProperty(document, 'hidden', { configurable: true, value: false })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('makes an initial request and exposes its successful data', async () => {
    const loader = vi.fn().mockResolvedValue({ status: 'online' })
    const { result } = renderHook(() => usePolling(loader))
    await act(async () => { await Promise.resolve() })
    expect(loader).toHaveBeenCalledTimes(1)
    expect(result.current.data).toEqual({ status: 'online' })
    expect(result.current.loading).toBe(false)
  })

  it('polls every five seconds by default', async () => {
    const loader = vi.fn().mockResolvedValue('ok')
    renderHook(() => usePolling(loader))
    await act(async () => { await Promise.resolve() })
    expect(loader).toHaveBeenCalledTimes(1)
    await act(async () => { await vi.advanceTimersByTimeAsync(4999) })
    expect(loader).toHaveBeenCalledTimes(1)
    await act(async () => { await vi.advanceTimersByTimeAsync(1) })
    expect(loader).toHaveBeenCalledTimes(2)
  })

  it('updates data after later successful polls', async () => {
    const loader = vi.fn().mockResolvedValueOnce('first').mockResolvedValueOnce('second')
    const { result } = renderHook(() => usePolling(loader, 5000))
    await act(async () => { await Promise.resolve() })
    expect(result.current.data).toBe('first')
    await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
    expect(result.current.data).toBe('second')
  })

  it('exposes request errors and clears them after success', async () => {
    const loader = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce('online')
    const { result } = renderHook(() => usePolling(loader, 5000))
    await act(async () => { await Promise.resolve() })
    expect(result.current.error).toHaveProperty('message', 'offline')
    await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
    expect(result.current.error).toBe(null)
    expect(result.current.data).toBe('online')
  })

  it('retries immediately when requested', async () => {
    const loader = vi.fn().mockResolvedValue('ready')
    const { result } = renderHook(() => usePolling(loader, 5000))
    await act(async () => { await Promise.resolve() })
    act(() => result.current.retry())
    await act(async () => { await Promise.resolve() })
    expect(loader).toHaveBeenCalledTimes(2)
  })

  it('does not call the API while the document is hidden', async () => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: true })
    const loader = vi.fn().mockResolvedValue('ok')
    renderHook(() => usePolling(loader, 5000))
    await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
    expect(loader).not.toHaveBeenCalled()
  })

  it('resumes polling when the document becomes visible', async () => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: true })
    const loader = vi.fn().mockResolvedValue('ok')
    renderHook(() => usePolling(loader, 5000))
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    Object.defineProperty(document, 'hidden', { configurable: true, value: false })
    act(() => document.dispatchEvent(new Event('visibilitychange')))
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(loader).toHaveBeenCalledTimes(1)
  })

  it('clears its timer and visibility listener on unmount', async () => {
    const removeSpy = vi.spyOn(document, 'removeEventListener')
    const loader = vi.fn().mockResolvedValue('ok')
    const { unmount } = renderHook(() => usePolling(loader))
    await act(async () => { await Promise.resolve() })
    unmount()
    expect(vi.getTimerCount()).toBe(0)
    expect(removeSpy).toHaveBeenCalledWith('visibilitychange', expect.any(Function))
  })
})
