const now = new Date()
const isoDaysAgo = (days, hour = 9) => {
  const date = new Date(now)
  date.setDate(date.getDate() - days)
  date.setHours(hour, 20, 0, 0)
  return date.toISOString()
}

export const mockUsers = [
  { id: 'usr-admin', username: 'admin', role: 'admin', is_active: true, created_at: isoDaysAgo(90) },
  { id: 'usr-reviewer', username: 'reviewer', role: 'reviewer', is_active: true, created_at: isoDaysAgo(55) },
  { id: 'usr-viewer', username: 'viewer', role: 'viewer', is_active: true, created_at: isoDaysAgo(40) },
  { id: 'usr-ops', username: 'ops.viewer', role: 'viewer', is_active: false, created_at: isoDaysAgo(25) },
]

export const mockAccounts = [
  { username: 'admin', password: 'demo-admin-123', role: 'admin' },
  { username: 'reviewer', password: 'demo-review-123', role: 'reviewer' },
  { username: 'viewer', password: 'demo-view-123', role: 'viewer' },
]

export const mockCameras = [
  { camera_id: 'cam-north', name: 'North Gate', location: 'North entrance', source_type: 'file', source_path: 'demo/north-gate.mp4', enabled: true, status: 'online', driver_side: 'right', camera_view: 'front', motorcycle_view: 'approaching', checks: ['helmet', 'seatbelt'], zone: [0.08, 0.72, 0.92, 0.72], created_at: isoDaysAgo(80), updated_at: isoDaysAgo(2) },
  { camera_id: 'cam-market', name: 'Market Road', location: 'Market crossing', source_type: 'rtsp', source_path: 'rtsp://operator:***@camera.local/live', enabled: true, status: 'offline', driver_side: 'left', camera_view: 'side_or_rear', motorcycle_view: 'receding', checks: ['helmet'], zone: [0.12, 0.68, 0.5, 0.6, 0.9, 0.7], created_at: isoDaysAgo(65), updated_at: isoDaysAgo(1) },
  { camera_id: 'cam-bridge', name: 'Bridge Approach', location: 'East bridge', source_type: 'file', source_path: 'demo/bridge-approach.mp4', enabled: false, status: 'error', driver_side: 'right', camera_view: 'front', motorcycle_view: 'approaching', checks: ['seatbelt'], zone: [0.05, 0.8, 0.95, 0.8], created_at: isoDaysAgo(33), updated_at: isoDaysAgo(4) },
]

const evidenceSvg = (id, label, color) => {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360"><rect width="640" height="360" fill="#101c2a"/><path d="M0 260h640M0 300h640" stroke="#354658" stroke-width="5"/><path d="M0 220 640 175" stroke="#73899b" stroke-width="3"/><rect x="252" y="98" width="132" height="178" rx="8" fill="#263e51" stroke="${color}" stroke-width="4"/><rect x="260" y="112" width="116" height="84" fill="none" stroke="${color}" stroke-width="4"/><text x="24" y="38" fill="#d8e4ed" font-family="Arial" font-size="18">MOCK EVIDENCE · ${id}</text><text x="24" y="336" fill="${color}" font-family="Arial" font-size="22">${label}</text></svg>`
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}
const evidencePath = (eventId, suffix) => `mock/evidence/${eventId}-${suffix}.svg`

const reasons = ['CLEAR_VIOLATION', 'TOO_FEW_OBSERVATIONS', 'CONFLICTING_OBSERVATIONS', 'UNCLEAR_OBSERVATIONS', 'LOW_CONFIDENCE']
export const mockViolations = Array.from({ length: 60 }, (_, index) => {
  const type = index % 2 === 0 ? 'helmet' : 'seatbelt'
  const pending = index % 6 === 0
  const camera = mockCameras[index % mockCameras.length]
  const eventId = `evt-${String(1000 + index).padStart(4, '0')}`
  const createdAt = isoDaysAgo(Math.floor(index / 2), 7 + (index % 12))
  const reason = pending ? reasons[1 + (index % 4)] : reasons[0]
  const evidence = {
    composite: evidencePath(eventId, pending ? 'needs-review' : `no-${type}`),
    full_frame: evidencePath(eventId, 'full-frame'),
    vehicle_crop: evidencePath(eventId, 'vehicle-crop'),
    driver_rider_crop: evidencePath(eventId, 'driver-rider-crop'),
  }
  const history = index % 4 === 0 ? [{ reviewed_by: 'reviewer', reviewed_at: isoDaysAgo(Math.max(0, Math.floor(index / 2) - 1)), final_decision: 'CONFIRMED_VIOLATION', review_note: 'Evidence reviewed.' }] : []
  const reviewed = history.length > 0
  return {
    event_id: eventId,
    camera_id: camera.camera_id,
    track_id: 40 + ((index * 7) % 120),
    violation_type: type,
    ai_result: pending ? 'unclear' : type === 'helmet' ? 'no_helmet' : 'no_seatbelt',
    detection_confidence: Number((0.62 + ((index * 13) % 36) / 100).toFixed(2)),
    reason_code: reason,
    evidence,
    review_status: pending ? 'pending' : reviewed ? 'confirmed' : 'not_required',
    final_decision: pending ? 'PENDING' : reviewed ? 'CONFIRMED_VIOLATION' : 'CONFIRMED_VIOLATION',
    reviewed_by: reviewed ? 'reviewer' : null,
    reviewed_at: reviewed ? history[0].reviewed_at : null,
    review_note: reviewed ? history[0].review_note : null,
    created_at: createdAt,
    review_history: history,
  }
})

export const mockSettings = {
  helmet_min_confidence: 0.4,
  seatbelt_min_confidence: 0.4,
  seatbelt_min_car_height: 120,
  duplicate_window_sec: 2,
  duplicate_iou_threshold: 0.5,
  max_workers: 1,
  frame_skip: 1,
  image_size: 640,
  evidence_retention_days: 30,
  extra: {},
}

export const evidencePlaceholder = (label = 'LIVE MOCK VIEW') => evidenceSvg('LIVE', label, '#34d399')
export const mockEvidencePlaceholder = (path) => {
  const label = path?.split('/').pop()?.replace('.svg', '').replaceAll('-', ' ').toUpperCase() || 'MOCK EVIDENCE'
  return evidenceSvg(path || 'MOCK', label, '#ef6572')
}
