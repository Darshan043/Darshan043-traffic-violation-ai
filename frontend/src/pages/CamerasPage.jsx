import { useCallback, useState } from 'react'
import { Camera, Pencil, Play, Plus, Trash2, Upload, VectorSquare } from 'lucide-react'
import { deleteCamera, listCameras, startCamera, stopCamera, updateCamera, uploadVideo } from '../api/index.js'
import { useAuth } from '../context/AuthContext.jsx'
import { can } from '../context/permissions.js'
import { useToast } from '../context/ToastContext.jsx'
import { useApiData } from '../hooks/useApiData.js'
import Badge from '../components/common/Badge.jsx'
import ConfirmDialog from '../components/common/ConfirmDialog.jsx'
import DataTable from '../components/common/DataTable.jsx'
import ErrorBox from '../components/common/ErrorBox.jsx'
import PageIntro from '../components/common/PageIntro.jsx'
import Panel from '../components/common/Panel.jsx'
import CameraForm from './CameraForm.jsx'
import ZoneEditor from './ZoneEditor.jsx'

const videoExtensions = ['.mp4', '.avi', '.mov', '.mkv']
const MAX_VIDEO_BYTES = 500 * 1024 * 1024

export default function CamerasPage() {
  const { user } = useAuth()
  const toast = useToast()
  const loadCameras = useCallback(() => listCameras(), [])
  const cameras = useApiData(loadCameras)
  const [editing, setEditing] = useState(null)
  const [formOpen, setFormOpen] = useState(false)
  const [zoneCamera, setZoneCamera] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [actionError, setActionError] = useState(null)
  const [upload, setUpload] = useState({ cameraId: '', percent: 0, error: null })
  const [failedUpload, setFailedUpload] = useState(null)
  const [busyId, setBusyId] = useState('')
  const admin = can(user?.role, 'manage_cameras')

  const replaceCamera = (updated) => cameras.setData((items) => items?.map((camera) => camera.camera_id === updated.camera_id ? updated : camera) || [updated])
  const changeEnabled = async (camera, enabled) => {
    setBusyId(camera.camera_id); setActionError(null)
    try { replaceCamera(await updateCamera(camera.camera_id, { enabled })); toast(`Camera ${enabled ? 'enabled' : 'disabled'}.`, 'success') }
    catch (error) { setActionError(error) }
    finally { setBusyId('') }
  }
  const toggleRun = async (camera) => {
    setBusyId(camera.camera_id); setActionError(null)
    try {
      const result = camera.status === 'processing' ? await stopCamera(camera.camera_id) : await startCamera(camera.camera_id)
      replaceCamera({ ...camera, status: result.status })
      toast(result.status === 'processing' ? 'Camera processing started.' : 'Camera stopped.', 'success')
    } catch (error) { setActionError(error) }
    finally { setBusyId('') }
  }
  const uploadFile = async (camera, file) => {
    if (!file) return
    setFailedUpload(null)
    const extension = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
    if (!videoExtensions.includes(extension)) { setUpload({ cameraId: '', percent: 0, error: new Error('Choose an MP4, AVI, MOV or MKV file.') }); return }
    if (file.size > MAX_VIDEO_BYTES) { setUpload({ cameraId: '', percent: 0, error: new Error('Video files must be 500 MB or smaller.') }); return }
    setUpload({ cameraId: camera.camera_id, percent: 0, error: null })
    try { const updated = await uploadVideo(camera.camera_id, file, (percent) => setUpload({ cameraId: camera.camera_id, percent, error: null })); replaceCamera(updated); setFailedUpload(null); toast('Video source uploaded.', 'success') }
    catch (error) { setFailedUpload({ camera, file }); setUpload({ cameraId: '', percent: 0, error }) }
    finally { window.setTimeout(() => setUpload((value) => value.cameraId === camera.camera_id ? { cameraId: '', percent: 0, error: value.error } : value), 700) }
  }
  const confirmDelete = async () => {
    if (!deleteTarget) return
    setBusyId(deleteTarget.camera_id); setActionError(null)
    try { await deleteCamera(deleteTarget.camera_id); cameras.setData((items) => items?.filter((camera) => camera.camera_id !== deleteTarget.camera_id)); toast('Camera deleted.', 'success'); setDeleteTarget(null) }
    catch (error) { setActionError(error) }
    finally { setBusyId('') }
  }

  const columns = [
    { key: 'name', label: 'Camera', render: (value, row) => <span className="camera-name-cell"><span className="camera-mini-icon"><Camera size={15} /></span><span><strong>{value}</strong><small>{row.camera_id} · {row.location || 'No location'}</small></span></span> },
    { key: 'source_type', label: 'Source', render: (value) => value === 'rtsp' ? 'RTSP stream' : 'Video file' },
    { key: 'status', label: 'Status', render: (value) => <Badge value={value} /> },
    { key: 'enabled', label: 'Enabled', render: (value, row) => <label className="switch-control"><input type="checkbox" aria-label={`Enable ${row.name}`} checked={value} disabled={!admin || busyId === row.camera_id} onChange={(event) => changeEnabled(row, event.target.checked)} /><span className="switch-track" /><span>{value ? 'On' : 'Off'}</span></label> },
    { key: 'actions', label: 'Actions', render: (_, row) => <div className="table-actions"><button className="icon-button table-icon" title="Edit camera" aria-label={`Edit ${row.name}`} type="button" disabled={!admin} onClick={() => { setEditing(row); setFormOpen(true) }}><Pencil size={15} /></button><button className="icon-button table-icon" title="Edit detection zone" aria-label={`Edit zone for ${row.name}`} type="button" disabled={!admin} onClick={() => setZoneCamera(row)}><VectorSquare size={15} /></button><button className="icon-button table-icon" title="Upload video source" aria-label={`Upload video for ${row.name}`} type="button" disabled={!admin} onClick={() => document.getElementById(`upload-${row.camera_id}`)?.click()}><Upload size={15} /></button>{admin && <><button className="icon-button table-icon" title={row.status === 'processing' ? 'Stop camera' : 'Start camera'} aria-label={`${row.status === 'processing' ? 'Stop' : 'Start'} ${row.name}`} type="button" disabled={busyId === row.camera_id} onClick={() => toggleRun(row)}><Play size={15} /></button><button className="icon-button table-icon danger-icon" title="Delete camera" aria-label={`Delete ${row.name}`} type="button" onClick={() => setDeleteTarget(row)}><Trash2 size={15} /></button></>}</div> },
  ]

  return <div className="page-stack">
    <PageIntro title="Camera management" description="Manage sources, checks, detection zones and camera state." action={admin && <button className="button button-primary" type="button" onClick={() => { setEditing(null); setFormOpen(true) }}><Plus size={16} />Add camera</button>} />
    {!admin && <p className="permission-note">Camera changes are restricted to administrators. You can still view camera status.</p>}
    {actionError && <ErrorBox error={actionError} onRetry={cameras.reload} />}{upload.error && <ErrorBox error={upload.error} onRetry={failedUpload ? () => uploadFile(failedUpload.camera, failedUpload.file) : undefined} />}
    {upload.cameraId && <div className="upload-progress" role="status"><span>Uploading video source · {upload.percent}%</span><progress value={upload.percent} max="100" /></div>}
    <Panel title="Configured cameras" subtitle="RTSP credentials are never displayed in this table."><DataTable columns={columns} rows={cameras.data || []} rowKey="camera_id" loading={cameras.loading} error={cameras.error} onRetry={cameras.reload} emptyTitle="No cameras configured" emptyDescription="Add a video or RTSP source to begin monitoring." /></Panel>
    {(cameras.data || []).map((camera) => <input key={camera.camera_id} id={`upload-${camera.camera_id}`} className="visually-hidden" type="file" aria-label={`Upload video for ${camera.name}`} accept={videoExtensions.join(',')} disabled={!admin} onChange={(event) => { uploadFile(camera, event.target.files?.[0]); event.target.value = '' }} />)}
    <CameraForm key={`${editing?.camera_id || 'new'}-${formOpen}`} camera={editing} open={formOpen} onClose={() => setFormOpen(false)} onSaved={(camera) => { if (editing) replaceCamera(camera); else cameras.setData((items) => [camera, ...(items || [])]) }} />
    {zoneCamera && admin && <ZoneEditor camera={zoneCamera} onClose={() => setZoneCamera(null)} onSaved={replaceCamera} />}
    <ConfirmDialog open={Boolean(deleteTarget)} title="Delete camera?" message={`Delete “${deleteTarget?.name}”? This removes the camera configuration.`} confirmLabel="Delete camera" danger onClose={() => setDeleteTarget(null)} onConfirm={confirmDelete} />
  </div>
}
