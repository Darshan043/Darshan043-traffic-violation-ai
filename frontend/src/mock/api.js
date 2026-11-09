import { evidencePlaceholder, mockAccounts, mockCameras, mockEvidencePlaceholder, mockSettings, mockUsers, mockViolations } from './data.js'

const wait = () => new Promise((resolve) => window.setTimeout(resolve, 160 + Math.random() * 360))
const maybeFail = (operation) => {
  if (sessionStorage.getItem('traffic_mock_error') === 'true') {
    const error = new Error(`Mock error: ${operation} failed on purpose. Turn off “Simulate API error” to retry.`)
    error.code = 'MOCK_ERROR'
    throw error
  }
}
const prepare = async (operation) => { await wait(); maybeFail(operation) }
const clone = (value) => structuredClone(value)
const byCamera = (id) => mockCameras.find((camera) => camera.camera_id === id)
const byViolation = (id) => mockViolations.find((violation) => violation.event_id === id)
const cameraResponse = (camera) => {
  const response = clone(camera)
  if (response.source_type === 'rtsp') response.source_path = response.source_path.replace(/(rtsp:\/\/[^:]+:)[^@]+(@)/i, '$1***$2')
  return response
}
const userResponse = (user) => ({ id: user.id, username: user.username, role: user.role, is_active: user.is_active, created_at: user.created_at })
const violationResponse = (violation) => {
  const response = { ...violation }
  delete response.review_history
  return clone(response)
}

export const mockApi = {
  async login({ username, password }) {
    await prepare('login')
    const account = mockAccounts.find((item) => item.username === username && item.password === password)
    if (!account) {
      const error = new Error('Invalid username or password')
      error.code = 'UNAUTHORIZED'
      error.status = 401
      throw error
    }
    const user = mockUsers.find((item) => item.username === username)
    return { access_token: `mock-token-${user.id}`, token_type: 'bearer', user: userResponse(user) }
  },
  async getMe() {
    await prepare('current user')
    const userId = sessionStorage.getItem('traffic_mock_user') || 'usr-admin'
    const user = mockUsers.find((item) => item.id === userId)
    if (!user) throw new Error('Mock session expired')
    return userResponse(user)
  },
  async listCameras() { await prepare('camera list'); return mockCameras.map(cameraResponse) },
  async createCamera(payload) {
    await prepare('create camera')
    const camera = { ...payload, status: 'offline', created_at: new Date().toISOString(), updated_at: new Date().toISOString() }
    mockCameras.unshift(camera)
    return cameraResponse(camera)
  },
  async updateCamera(id, payload) {
    await prepare('update camera')
    const camera = byCamera(id)
    if (!camera) throw new Error('Camera not found')
    Object.assign(camera, payload, { updated_at: new Date().toISOString() })
    return cameraResponse(camera)
  },
  async deleteCamera(id) {
    await prepare('delete camera')
    const index = mockCameras.findIndex((camera) => camera.camera_id === id)
    if (index >= 0) mockCameras.splice(index, 1)
    return null
  },
  async uploadVideo(id, _file, onProgress) {
    await prepare('video upload')
    const camera = byCamera(id)
    if (!camera) throw new Error('Camera not found')
    camera.source_type = 'file'
    camera.source_path = `mock-upload/${id}-clip.mp4`
    camera.updated_at = new Date().toISOString()
    onProgress?.(100)
    return cameraResponse(camera)
  },
  async saveZone(id, points) {
    await prepare('save detection zone')
    const camera = byCamera(id)
    if (!camera) throw new Error('Camera not found')
    camera.zone = clone(points)
    camera.updated_at = new Date().toISOString()
    return cameraResponse(camera)
  },
  async getSnapshot() {
    await prepare('camera snapshot')
    return fetch(evidencePlaceholder('SNAPSHOT · MOCK')).then((response) => response.blob())
  },
  async getEvidence(path) {
    await prepare('evidence image')
    return fetch(mockEvidencePlaceholder(path)).then((response) => response.blob())
  },
  async startCamera(id) {
    await prepare('start camera')
    const camera = byCamera(id)
    if (!camera) throw new Error('Camera not found')
    camera.status = 'processing'
    return { camera_id: id, status: 'processing' }
  },
  async stopCamera(id) {
    await prepare('stop camera')
    const camera = byCamera(id)
    if (!camera) throw new Error('Camera not found')
    camera.status = 'offline'
    return { camera_id: id, status: 'offline' }
  },
  async getStatus(id) {
    await prepare('camera status')
    const camera = byCamera(id)
    if (!camera) throw new Error('Camera not found')
    return { camera_id: id, status: camera.status }
  },
  async listViolations(params = {}) {
    await prepare('violation list')
    const page = Number(params.page || 1)
    const limit = Number(params.limit || 50)
    let items = [...mockViolations]
    if (params.type) items = items.filter((item) => item.violation_type === params.type)
    if (params.result === 'violation') items = items.filter((item) => item.ai_result === 'no_helmet' || item.ai_result === 'no_seatbelt')
    else if (params.result === 'needs_review' || params.result === 'NEEDS_REVIEW') items = items.filter((item) => item.ai_result === 'unclear')
    else if (params.result) items = items.filter((item) => item.ai_result === params.result)
    if (params.camera) items = items.filter((item) => item.camera_id === params.camera)
    if (params.track_id) items = items.filter((item) => item.track_id === Number(params.track_id))
    if (params.review_status === 'UNREVIEWED') items = items.filter((item) => ['pending', 'not_required', 'UNREVIEWED'].includes(item.review_status))
    else if (params.review_status === 'REVIEWED') items = items.filter((item) => ['confirmed', 'rejected', 'REVIEWED'].includes(item.review_status))
    else if (params.review_status) items = items.filter((item) => item.review_status === params.review_status)
    if (params.date_from) items = items.filter((item) => item.created_at >= params.date_from)
    if (params.date_to) items = items.filter((item) => item.created_at <= params.date_to)
    const total = items.length
    return { items: clone(items.slice((page - 1) * limit, page * limit)), total, page, limit }
  },
  async getViolation(id) {
    await prepare('violation details')
    const violation = byViolation(id)
    if (!violation) throw new Error('Violation not found')
    return violationResponse(violation)
  },
  async reviewViolation(id, payload) {
    await prepare('violation review')
    const violation = byViolation(id)
    if (!violation) throw new Error('Violation not found')
    const reviewedAt = new Date().toISOString()
    Object.assign(violation, {
      review_status: payload.final_decision === 'NOT_A_VIOLATION' ? 'rejected' : 'confirmed',
      final_decision: payload.final_decision,
      reviewed_by: sessionStorage.getItem('traffic_mock_username') || 'admin',
      reviewed_at: reviewedAt,
      review_note: payload.review_note || null,
      review_history: [...violation.review_history, { reviewed_by: sessionStorage.getItem('traffic_mock_username') || 'admin', reviewed_at: reviewedAt, final_decision: payload.final_decision, review_note: payload.review_note || null }],
    })
    return violationResponse(violation)
  },
  async exportViolationsCsv(params = {}) {
    await prepare('CSV export')
    const { items } = await this.listViolations({ ...params, page: 1, limit: 500 })
    const columns = ['event_id', 'camera_id', 'track_id', 'violation_type', 'ai_result', 'detection_confidence', 'reason_code', 'review_status', 'final_decision', 'reviewed_by', 'reviewed_at', 'review_note', 'created_at']
    const csv = [columns.join(','), ...items.map((item) => columns.map((key) => `"${String(item[key] ?? '').replaceAll('"', '""')}"`).join(','))].join('\r\n')
    return new Blob([csv], { type: 'text/csv' })
  },
  async statsSummary() {
    await prepare('summary statistics')
    const needsReview = mockViolations.filter((item) => item.ai_result === 'unclear').length
    const compliant = 84
    const violationCount = mockViolations.length - needsReview
    return { total_vehicles: compliant + violationCount + needsReview, compliant_vehicles: compliant, violations: violationCount, needs_review: needsReview, compliance_percentage: Number((compliant / (compliant + violationCount) * 100).toFixed(2)), reviewed_count: 10, unreviewed_count: needsReview, helmet_compliance_percentage: 91.7, seatbelt_compliance_percentage: 88.2, review_count: needsReview }
  },
  async statsDaily() {
    await prepare('daily statistics')
    return Array.from({ length: 30 }, (_, index) => {
      const date = new Date()
      date.setDate(date.getDate() - index)
      const violations = 3 + ((index * 7) % 11)
      const compliant = 15 + ((index * 11) % 30)
      return { date: date.toISOString().slice(0, 10), total_vehicles: compliant + violations + 2, compliant_vehicles: compliant, violations, needs_review: 2, compliance_percentage: Number((compliant / (compliant + violations) * 100).toFixed(2)) }
    })
  },
  async statsCameras() {
    await prepare('camera statistics')
    return mockCameras.map((camera, index) => ({ camera_id: camera.camera_id, camera_name: camera.name, total_vehicles: 70 - index * 12, compliant_vehicles: 49 - index * 7, violations: 18 - index * 4, needs_review: 3, compliance_percentage: Number(((49 - index * 7) / (67 - index * 11) * 100).toFixed(2)) }))
  },
  async getSettings() { await prepare('settings'); return clone(mockSettings) },
  async putSettings(payload) { await prepare('save settings'); Object.assign(mockSettings, payload); return clone(mockSettings) },
  async listUsers() { await prepare('user list'); return clone(mockUsers.map(userResponse)) },
  async createUser(payload) {
    await prepare('create user')
    const user = { id: `usr-${crypto.randomUUID()}`, username: payload.username, role: payload.role || 'viewer', is_active: true, created_at: new Date().toISOString() }
    mockUsers.push(user)
    return userResponse(user)
  },
  async updateUser(id, payload) {
    await prepare('update user')
    const user = mockUsers.find((item) => item.id === id)
    if (!user) throw new Error('User not found')
    Object.assign(user, payload)
    return userResponse(user)
  },
  async health() { await prepare('health'); return { status: 'ok' } },
}
