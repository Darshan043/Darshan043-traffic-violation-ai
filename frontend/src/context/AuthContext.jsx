import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { clearToken, getToken, setToken } from '../api/client.js'
import { getMe, isMockMode, login as loginRequest } from '../api/index.js'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(Boolean(getToken()))

  useEffect(() => {
    if (!getToken()) return
    let active = true
    getMe().then((currentUser) => { if (active) setUser(currentUser) })
      .catch(() => { clearToken(); if (isMockMode()) sessionStorage.removeItem('traffic_mock_user') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  const login = useCallback(async (credentials) => {
    const result = await loginRequest(credentials)
    setToken(result.access_token)
    if (isMockMode()) {
      sessionStorage.setItem('traffic_mock_user', result.user.id)
      sessionStorage.setItem('traffic_mock_username', result.user.username)
    }
    setUser(result.user)
    return result.user
  }, [])

  const logout = useCallback(() => {
    clearToken()
    sessionStorage.removeItem('traffic_mock_user')
    sessionStorage.removeItem('traffic_mock_username')
    setUser(null)
  }, [])

  const value = useMemo(() => ({ user, loading, login, logout, isMock: isMockMode() }), [user, loading, login, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}
