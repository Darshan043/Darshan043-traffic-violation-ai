import { apiUrl, request } from './client.js'
import { mockApi } from '../mock/api.js'
import { connectMockSocket } from '../mock/socket.js'

export const isMockMode = () => import.meta.env.VITE_USE_MOCK !== 'false'
export const setMockError = (enabled) => sessionStorage.setItem('traffic_mock_error', String(Boolean(enabled)))
export const getMockError = () => sessionStorage.getItem('traffic_mock_error') === 'true'
export const connectMockAlerts = (onMessage, onStatus) => connectMockSocket(onMessage, onStatus)

const queryString = (params = {}) => {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') query.set(key, String(value))
  })
  const value = query.toString()
  return value ? `?${value}` : ''
}
const dispatch = (name, args, real) => isMockMode() ? mockApi[name](...args) : real()

export const login = (payload) => dispatch('login', [payload], () => request('/api/auth/login', { method: 'POST', body: JSON.stringify(payload) }))
export const getMe = () => dispatch('getMe', [], () => request('/api/auth/me'))
export const listCameras = () => dispatch('listCameras', [], () => request('/api/cameras'))
export const createCamera = (payload) => dispatch('createCamera', [payload], () => request('/api/cameras', { method: 'POST', body: JSON.stringify(payload) }))
export const updateCamera = (id, payload) => dispatch('updateCamera', [id, payload], () => request(`/api/cameras/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(payload) }))
export const deleteCamera = (id) => dispatch('deleteCamera', [id], () => request(`/api/cameras/${encodeURIComponent(id)}`, { method: 'DELETE' }))
export const uploadVideo = (id, file, onProgress) => {
  if (isMockMode()) return mockApi.uploadVideo(id, file, onProgress)
  return new Promise((resolve, reject) => {
    const form = new FormData()
    form.append('file', file)
    const xhr = new XMLHttpRequest()
    xhr.open('POST', apiUrl(`/api/cameras/${encodeURIComponent(id)}/video`))
    const token = sessionStorage.getItem('traffic_access_token')
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)
    xhr.upload.onprogress = (event) => { if (event.lengthComputable) onProgress?.(Math.round((event.loaded / event.total) * 100)) }
    xhr.onerror = () => reject(new Error('Could not reach the server during upload.'))
    xhr.onload = () => {
      let body = {}
      try { body = JSON.parse(xhr.responseText) } catch { /* Response may be empty. */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body)
      else reject(new Error(body.message || `Upload failed (${xhr.status})`))
    }
    xhr.send(form)
  })
}
export const saveZone = (id, points) => dispatch('saveZone', [id, points], () => request(`/api/cameras/${encodeURIComponent(id)}/zone`, { method: 'PUT', body: JSON.stringify({ points }) }))
export const getSnapshot = (id) => dispatch('getSnapshot', [id], () => request(`/api/cameras/${encodeURIComponent(id)}/snapshot`, { responseType: 'blob' }))
export const getEvidence = (path) => dispatch('getEvidence', [path], () => request(`/evidence/${path.split('/').map(encodeURIComponent).join('/')}`, { responseType: 'blob' }))
export const startCamera = (id) => dispatch('startCamera', [id], () => request(`/api/cameras/${encodeURIComponent(id)}/start`, { method: 'POST' }))
export const stopCamera = (id) => dispatch('stopCamera', [id], () => request(`/api/cameras/${encodeURIComponent(id)}/stop`, { method: 'POST' }))
export const getStatus = (id) => dispatch('getStatus', [id], () => request(`/api/cameras/${encodeURIComponent(id)}/status`))
export const listViolations = (params) => dispatch('listViolations', [params], () => request(`/api/violations${queryString(params)}`))
export const getViolation = (id) => dispatch('getViolation', [id], () => request(`/api/violations/${encodeURIComponent(id)}`))
export const reviewViolation = (id, payload) => dispatch('reviewViolation', [id, payload], () => request(`/api/violations/${encodeURIComponent(id)}/review`, { method: 'PUT', body: JSON.stringify(payload) }))
export const exportViolationsCsv = (params) => dispatch('exportViolationsCsv', [params], () => request(`/api/violations/export${queryString(params)}`, { responseType: 'blob' }))
export const statsSummary = () => dispatch('statsSummary', [], () => request('/api/stats/summary'))
export const statsDaily = () => dispatch('statsDaily', [], () => request('/api/stats/daily'))
export const statsCameras = () => dispatch('statsCameras', [], () => request('/api/stats/cameras'))
export const getSettings = () => dispatch('getSettings', [], () => request('/api/settings'))
export const putSettings = (payload) => dispatch('putSettings', [payload], () => request('/api/settings', { method: 'PUT', body: JSON.stringify(payload) }))
export const listUsers = () => dispatch('listUsers', [], () => request('/api/users'))
export const createUser = (payload) => dispatch('createUser', [payload], () => request('/api/users', { method: 'POST', body: JSON.stringify(payload) }))
export const updateUser = (id, payload) => dispatch('updateUser', [id, payload], () => request(`/api/users/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify(payload) }))
export const disableUser = (id) => dispatch('updateUser', [id, { is_active: false }], () => request(`/api/users/${encodeURIComponent(id)}`, { method: 'DELETE' }))
export const health = () => dispatch('health', [], () => request('/api/health'))

export function streamUrl(cameraId) {
  const base = apiUrl(`/api/stream/${encodeURIComponent(cameraId)}`)
  return `${base}?token=${encodeURIComponent(sessionStorage.getItem('traffic_access_token') || '')}`
}
