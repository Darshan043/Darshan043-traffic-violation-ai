import { useState } from 'react'
import { createCamera, updateCamera } from '../api/index.js'
import { useToast } from '../context/ToastContext.jsx'
import Modal from '../components/common/Modal.jsx'
import ErrorBox from '../components/common/ErrorBox.jsx'

const blank = { camera_id: '', name: '', location: '', source_type: 'file', source_path: '', enabled: true, driver_side: 'right', camera_view: 'unknown', motorcycle_view: 'approaching', checks: ['helmet', 'seatbelt'], zone: [0, 0.9, 1, 0.9] }

export default function CameraForm({ camera, open, onClose, onSaved }) {
  const initialForm = camera ? { ...camera, source_path: camera.source_type === 'rtsp' ? '' : camera.source_path, checks: [...camera.checks] } : blank
  const [form, setForm] = useState(initialForm)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const toast = useToast()
  const editing = Boolean(camera)
  const set = (key, value) => setForm((state) => ({ ...state, [key]: value }))
  const toggleCheck = (check) => setForm((state) => ({ ...state, checks: state.checks.includes(check) ? state.checks.filter((item) => item !== check) : [...state.checks, check] }))
  const save = async (event) => {
    event.preventDefault(); setError(null)
    if (form.source_type === 'rtsp' && !form.source_path.trim()) { setError(new Error('Enter the RTSP URL for this camera. The saved password is never shown in edit mode.')); return }
    setSaving(true)
    try {
      const payload = { name: form.name, location: form.location, source_type: form.source_type, enabled: form.enabled, driver_side: form.driver_side, camera_view: form.camera_view, motorcycle_view: form.motorcycle_view, checks: form.checks, zone: form.zone }
      if (form.source_path.trim() || (editing && form.source_type !== camera.source_type)) payload.source_path = form.source_path.trim()
      const result = editing ? await updateCamera(camera.camera_id, payload) : await createCamera({ ...payload, camera_id: form.camera_id, source_path: form.source_path.trim() })
      toast(editing ? 'Camera updated.' : 'Camera added.', 'success'); onSaved(result); onClose()
    } catch (reason) { setError(reason) }
    finally { setSaving(false) }
  }
  return <Modal title={editing ? 'Edit camera' : 'Add camera'} open={open} onClose={onClose}><form className="camera-form" onSubmit={save}>
    {!editing && <label className="form-label">Camera ID<input className="field-input" required minLength="1" maxLength="50" value={form.camera_id} onChange={(event) => set('camera_id', event.target.value)} /></label>}
    <label className="form-label">Name<input className="field-input" required maxLength="100" value={form.name} onChange={(event) => set('name', event.target.value)} /></label>
    <label className="form-label">Location<input className="field-input" value={form.location} onChange={(event) => set('location', event.target.value)} /></label>
    <label className="form-label">Source type<select className="field-input" value={form.source_type} onChange={(event) => set('source_type', event.target.value)}><option value="file">Video file</option><option value="rtsp">RTSP camera</option></select></label>
    {form.source_type === 'rtsp' ? <label className="form-label">RTSP URL<input className="field-input" type="password" autoComplete="new-password" placeholder={editing ? 'Enter URL again to replace saved source' : 'rtsp://user:password@host/stream'} value={form.source_path} onChange={(event) => set('source_path', event.target.value)} /><small>Passwords are hidden while typing and are never prefilled.</small></label> : <label className="form-label">Source file path<input className="field-input" placeholder="Local video source path" value={form.source_path} onChange={(event) => set('source_path', event.target.value)} /></label>}
    <div className="form-grid-two"><label className="form-label">Driver side<select className="field-input" value={form.driver_side} onChange={(event) => set('driver_side', event.target.value)}><option value="left">Left</option><option value="right">Right</option></select></label><label className="form-label">Camera view<select className="field-input" value={form.camera_view} onChange={(event) => set('camera_view', event.target.value)}><option value="front">Front</option><option value="side_or_rear">Side or rear</option><option value="unknown">Unknown</option></select></label><label className="form-label">Motorcycle view<select className="field-input" value={form.motorcycle_view} onChange={(event) => set('motorcycle_view', event.target.value)}><option value="approaching">Approaching</option><option value="receding">Receding</option></select></label></div>
    <fieldset className="check-fieldset"><legend>Checks</legend>{['helmet', 'seatbelt'].map((check) => <label key={check}><input type="checkbox" checked={form.checks.includes(check)} onChange={() => toggleCheck(check)} />{check[0].toUpperCase() + check.slice(1)}</label>)}</fieldset>
    {error && <ErrorBox error={error} />}
    <div className="modal-actions"><button type="button" className="button button-secondary" onClick={onClose}>Cancel</button><button className="button button-primary" disabled={saving}>{saving ? 'Saving…' : editing ? 'Save changes' : 'Add camera'}</button></div>
  </form></Modal>
}
