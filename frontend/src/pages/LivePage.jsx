import { useCallback, useMemo, useState } from 'react'
import { Activity, Minus, Plus, RotateCcw, Signal, SignalZero } from 'lucide-react'
import { getStatus, listCameras, listViolations, startCamera, stopCamera, streamUrl } from '../api/index.js'
import { useAuth } from '../context/AuthContext.jsx'
import { can } from '../context/permissions.js'
import Badge from '../components/common/Badge.jsx'
import EmptyState from '../components/common/EmptyState.jsx'
import ErrorBox from '../components/common/ErrorBox.jsx'
import EvidenceImage from '../components/common/EvidenceImage.jsx'
import Loader from '../components/common/Loader.jsx'
import Modal from '../components/common/Modal.jsx'
import PageIntro from '../components/common/PageIntro.jsx'
import Panel from '../components/common/Panel.jsx'
import LiveCanvas from '../components/live/LiveCanvas.jsx'
import { useApiData } from '../hooks/useApiData.js'
import { usePolling } from '../hooks/usePolling.js'
import { useLiveAlerts } from '../context/LiveAlertsContext.jsx'
import { formatDate } from '../utils/format.js'

export default function LivePage() {
  const { user, isMock } = useAuth()
  const loadCameras = useCallback(() => listCameras(), [])
  const cameras = useApiData(loadCameras)
  const [cameraId, setCameraId] = useState('')
  const selected = cameras.data?.find((camera) => camera.camera_id === cameraId) || cameras.data?.[0]
  const selectedCameraId = selected?.camera_id
  const loadStatus = useCallback(() => selectedCameraId ? getStatus(selectedCameraId) : Promise.resolve(null), [selectedCameraId])
  const statusPoll = usePolling(loadStatus, 5000, Boolean(selectedCameraId))
  const status = statusPoll.data
  const [actionError, setActionError] = useState(null)
  const statusError = statusPoll.error || actionError
  const statusLoading = statusPoll.loading
  const retry = statusPoll.retry
  const [alertId, setAlertId] = useState(null)
  const [zoom, setZoom] = useState(1)
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [drag, setDrag] = useState(null)
  const [busy, setBusy] = useState(false)
  const loadAlerts = useCallback(() => listViolations({ camera: selected?.camera_id, page: 1, limit: 50 }), [selected?.camera_id])
  const alerts = useApiData(loadAlerts)
  const { alerts: socketAlerts } = useLiveAlerts()
  const liveItems = useMemo(() => {
    const items = [...(socketAlerts || []).filter((item) => !selectedCameraId || item.camera_id === selectedCameraId), ...(alerts.data?.items || [])]
    return [...new Map(items.map((item) => [item.event_id, item])).values()].slice(0, 50)
  }, [alerts.data, socketAlerts, selectedCameraId])
  const selectedAlert = useMemo(() => liveItems.find((item) => item.event_id === alertId), [liveItems, alertId])

  const streamError = () => window.setTimeout(() => retry(), 3000)
  const resetView = () => { setZoom(1); setPan({ x: 0, y: 0 }) }
  const changeZoom = (amount) => setZoom((value) => Math.min(3, Math.max(1, Number((value + amount).toFixed(2)))))
  const onWheel = (event) => { event.preventDefault(); changeZoom(event.deltaY < 0 ? 0.1 : -0.1) }
  const onPointerDown = (event) => { event.currentTarget.setPointerCapture(event.pointerId); setDrag({ x: event.clientX - pan.x, y: event.clientY - pan.y }) }
  const onPointerMove = (event) => { if (drag) setPan({ x: event.clientX - drag.x, y: event.clientY - drag.y }) }
  const onAction = async (action) => {
    setBusy(true)
    try { setActionError(null); await (action === 'start' ? startCamera(selected.camera_id) : stopCamera(selected.camera_id)); retry(); cameras.reload() }
    catch (error) { setActionError(error) }
    finally { setBusy(false) }
  }
  const statusValue = status?.status || selected?.status || 'offline'
  const isConnected = ['online', 'processing'].includes(statusValue)

  return <div className="page-stack">
    <PageIntro title="Live monitoring" description="Watch a camera feed, status and incoming safety alerts." action={cameras.data?.length > 0 && <label className="filter-field camera-select">Camera<select value={selected?.camera_id || ''} onChange={(event) => { setCameraId(event.target.value); setZoom(1); setPan({ x: 0, y: 0 }) }}>{cameras.data.map((camera) => <option key={camera.camera_id} value={camera.camera_id}>{camera.name}</option>)}</select></label>} />
    {cameras.loading ? <Panel title="Camera feed"><Loader label="Loading cameras" /></Panel> : cameras.error ? <Panel title="Camera feed"><ErrorBox error={cameras.error} onRetry={cameras.reload} /></Panel> : !selected ? <EmptyState title="No cameras configured" description="Add a camera in Camera Management to begin monitoring." /> : <div className="live-layout">
      <div className="page-stack">
        <Panel title={selected.name} subtitle={`${selected.location} · ${selected.camera_id}`} action={can(user?.role, 'manage_cameras') && <div className="button-row"><button className="button button-primary" type="button" disabled={busy || statusValue === 'processing'} onClick={() => onAction('start')}>Start</button><button className="button button-secondary" type="button" disabled={busy || statusValue !== 'processing'} onClick={() => onAction('stop')}>Stop</button></div>}>
          {statusError && <ErrorBox error={statusError} onRetry={retry} />}
          {statusLoading && !status && <Loader label="Checking camera status" />}
          <div className="video-toolbar"><span className="video-camera-name"><Activity size={15} /> {selected.name}</span><div className="zoom-actions"><button type="button" title="Zoom out" aria-label="Zoom out" className="icon-button" onClick={() => changeZoom(-0.1)}><Minus size={16} /></button><span>{Math.round(zoom * 100)}%</span><button type="button" title="Zoom in" aria-label="Zoom in" className="icon-button" onClick={() => changeZoom(0.1)}><Plus size={16} /></button><button type="button" title="Reset zoom and pan" aria-label="Reset zoom and pan" className="icon-button" onClick={resetView}><RotateCcw size={15} /></button></div></div>
          <div className={`video-viewport${drag ? ' is-dragging' : ''}`} onWheel={onWheel} onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={() => setDrag(null)} onPointerCancel={() => setDrag(null)}>
            {isConnected ? <div className="video-transform" style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})` }}>{isMock ? <LiveCanvas cameraName={selected.name} /> : <img key={`${selected.camera_id}-${retry}`} className="real-stream" src={streamUrl(selected.camera_id)} alt={`Live camera stream from ${selected.name}`} onError={streamError} />}</div> : <div className="no-signal"><SignalZero size={33} /><strong>NO SIGNAL</strong><span>{statusValue === 'error' ? 'Camera reported an error.' : 'This camera is disconnected.'}</span><button type="button" className="button button-secondary" onClick={retry}>Retry connection</button></div>}
            {isConnected && <span className="live-tag"><span className="status-indicator status-green" />LIVE</span>}
          </div>
          <div className="video-status"><span className={isConnected ? 'text-connected' : 'text-disconnected'}>{isConnected ? <Signal size={14} /> : <SignalZero size={14} />}{isConnected ? 'Connected' : 'Disconnected'}</span><span>FPS <b>—</b><small>Not provided by backend</small></span><span>Tracked vehicles <b>—</b><small>Not provided by backend</small></span>{statusValue === 'processing' && <Badge value="processing" label="Pass indicator is in stream" />}</div>
        </Panel>
        <Panel title="Camera status" subtitle="Status is refreshed every five seconds; polling pauses in a hidden tab."><div className="status-summary"><div><span>Connection</span><Badge value={statusValue} /></div><div><span>Checks enabled</span><strong>{selected.checks.map((item) => item[0].toUpperCase() + item.slice(1)).join(' · ') || '—'}</strong></div><div><span>Camera view</span><strong>{selected.camera_view.replaceAll('_', ' ')}</strong></div></div></Panel>
      </div>
      <Panel title="Live alerts" subtitle="Newest first · select one to inspect evidence" className="live-alerts-panel">
        {alerts.loading ? <Loader label="Loading camera alerts" /> : alerts.error && liveItems.length === 0 ? <ErrorBox error={alerts.error} onRetry={alerts.reload} /> : liveItems.length ? <div className="alert-list">{liveItems.map((item) => <button key={item.event_id} type="button" className="alert-row alert-button" onClick={() => setAlertId(item.event_id)}><span className="alert-symbol"><Activity size={14} /></span><span className="alert-copy"><strong>{item.ai_result === 'unclear' ? 'Needs review' : `No ${item.violation_type}`}</strong><small>Track {item.track_id}</small></span><time>{formatDate(item.created_at, { dateStyle: 'short', timeStyle: 'short' })}</time></button>)}</div> : <EmptyState title="No alerts for this camera" description="Alerts will appear here when the camera reports an event." />}
      </Panel>
    </div>}
    <Modal title="Alert evidence" open={Boolean(selectedAlert)} onClose={() => setAlertId(null)} drawer><div className="evidence-detail"><EvidenceImage path={selectedAlert?.evidence?.composite} alt={`Evidence for ${selectedAlert?.event_id}`} className="evidence-large" /><p><strong>{selectedAlert?.event_id}</strong> · Track {selectedAlert?.track_id}</p><p>{selectedAlert ? formatDate(selectedAlert.created_at) : ''}</p></div></Modal>
  </div>
}
