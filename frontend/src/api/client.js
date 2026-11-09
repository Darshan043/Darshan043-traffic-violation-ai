const BASE = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '')
const TOKEN_KEY = 'traffic_access_token'

export const getToken = () => sessionStorage.getItem(TOKEN_KEY)
export const setToken = (token) => sessionStorage.setItem(TOKEN_KEY, token)
export const clearToken = () => sessionStorage.removeItem(TOKEN_KEY)

export class ApiError extends Error {
  constructor(message, status = 0, code = 'NETWORK_ERROR') {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

export async function request(path, options = {}) {
  const headers = new Headers(options.headers || {})
  const token = getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  let response
  try {
    response = await fetch(`${BASE}${path}`, { ...options, headers })
  } catch {
    throw new ApiError('Could not reach the server. Check your connection and try again.')
  }

  if (response.status === 401) {
    clearToken()
    if (window.location.pathname !== '/login') window.location.assign('/login')
  }
  if (response.status === 403) {
    throw new ApiError('You do not have permission to do that.', 403, 'FORBIDDEN')
  }

  if (!response.ok) {
    let payload = {}
    try { payload = await response.json() } catch { /* Non-JSON error body. */ }
    throw new ApiError(payload.message || `Request failed (${response.status})`, response.status, payload.error || 'HTTP_ERROR')
  }
  if (response.status === 204) return null
  if (options.responseType === 'blob') return response.blob()
  if (options.responseType === 'text') return response.text()
  const contentType = response.headers.get('content-type') || ''
  return contentType.includes('application/json') ? response.json() : response.blob()
}

export const apiUrl = (path) => `${BASE}${path}`
