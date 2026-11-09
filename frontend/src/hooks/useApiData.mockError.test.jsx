import { act, renderHook } from '@testing-library/react'
import { useCallback } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { listCameras, setMockError } from '../api/index.js'
import { useApiData } from './useApiData.js'

describe('mock error switch with data hooks', () => {
  afterEach(() => {
    setMockError(false)
    vi.useRealTimers()
  })

  it('surfaces a mock API failure through the loading, error and retry states', async () => {
    vi.useFakeTimers()
    setMockError(true)
    const { result } = renderHook(() => useApiData(useCallback(() => listCameras(), [])))
    expect(result.current.loading).toBe(true)
    await act(async () => { await vi.advanceTimersByTimeAsync(600) })
    expect(result.current.loading).toBe(false)
    expect(result.current.error).toHaveProperty('code', 'MOCK_ERROR')
    setMockError(false)
    act(() => result.current.reload())
    await act(async () => { await vi.advanceTimersByTimeAsync(600) })
    expect(result.current.error).toBe(null)
    expect(result.current.data.length).toBeGreaterThan(0)
  })
})
