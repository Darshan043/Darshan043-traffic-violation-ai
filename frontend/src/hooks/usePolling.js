
import { useCallback, useEffect, useState } from 'react'

// Runs a request on an interval and stops work while the browser tab is hidden.
export function usePolling(loader, interval = 5000, enabled = true) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(Boolean(enabled))
  const [version, setVersion] = useState(0)

  const retry = useCallback(() => {
    setLoading(true)
    setVersion((value) => value + 1)
  }, [])

  useEffect(() => {
    if (!enabled) return undefined

    let active = true
    let timer

    const poll = async () => {
      if (document.hidden) {
        timer = window.setTimeout(poll, 1000)
        return
      }

      try {
        const result = await loader()

        if (active) {
          setData(result)
          setError(null)
        }
      } catch (reason) {
        if (active) setError(reason)
      } finally {
        if (active) {
          setLoading(false)
          timer = window.setTimeout(poll, interval)
        }
      }
    }

    const onVisibility = () => {
      if (!document.hidden) {
        window.clearTimeout(timer)
        timer = window.setTimeout(poll, 0)
      }
    }

    document.addEventListener('visibilitychange', onVisibility)
    poll()

    return () => {
      active = false
      window.clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [loader, interval, enabled, version])

  return {
    data,
    error,
    loading: Boolean(enabled) && loading,
    retry,
  }
}

