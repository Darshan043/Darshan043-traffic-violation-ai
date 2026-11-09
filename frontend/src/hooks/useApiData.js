import { useCallback, useEffect, useState } from 'react'

export function useApiData(loader, dependencies = []) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [version, setVersion] = useState(0)
  const reload = useCallback(() => setVersion((value) => value + 1), [])
  // This effect intentionally marks the request pending when its loader or inputs change.
  useEffect(() => {
    let active = true
    // A new fetch cycle must switch the data region back to its loading state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true)
    setError(null)
    loader().then((result) => { if (active) setData(result) })
      .catch((reason) => { if (active) setError(reason) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loader, version, ...dependencies])
  return { data, setData, loading, error, reload }
}
