import { useCallback, useEffect, useMemo, useState } from 'react'
import { getSnapshot, saveZone } from '../api/index.js'
import { useToast } from '../context/ToastContext.jsx'
import { useApiData } from '../hooks/useApiData.js'
import EmptyState from '../components/common/EmptyState.jsx'
import ErrorBox from '../components/common/ErrorBox.jsx'
import Loader from '../components/common/Loader.jsx'
import Modal from '../components/common/Modal.jsx'
import { pixelsToNormalized } from '../utils/zoneCoordinates.js'

export default function ZoneEditor({ camera, onClose, onSaved }) {
  const [points, setPoints] = useState(() => Array.from({ length: Math.floor((camera?.zone?.length || 0) / 2) }, (_, index) => [camera.zone[index * 2], camera.zone[index * 2 + 1]]))
  const [snapshotUrl, setSnapshotUrl] = useState('')
  const [aspectRatio, setAspectRatio] = useState(16 / 9)
  const [saveError, setSaveError] = useState(null)
  const [saving, setSaving] = useState(false)
  const toast = useToast()
  const cameraId = camera?.camera_id
  const loader = useCallback(() => cameraId ? getSnapshot(cameraId) : Promise.resolve(null), [cameraId])
  const snapshot = useApiData(loader)

  useEffect(() => {
    if (!snapshot.data) return undefined
    const url = URL.createObjectURL(snapshot.data)
    // The object URL is created from an async API result and synchronized to the image element.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSnapshotUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [snapshot.data])

  const flattened = useMemo(() => points.flatMap(([x, y]) => [x, y]), [points])
  const isPolygon = points.length >= 3
  const clickPoint = (event) => {
    const rect = event.currentTarget.getBoundingClientRect()
    const [point] = pixelsToNormalized([[event.clientX - rect.left, event.clientY - rect.top]], rect.width, rect.height)
    setPoints((value) => [...value, point])
  }
  const save = async () => {
    setSaving(true); setSaveError(null)
    try { const updated = await saveZone(camera.camera_id, flattened); onSaved(updated); toast('Detection zone saved.', 'success'); onClose() }
    catch (error) { setSaveError(error) }
    finally { setSaving(false) }
  }

  return <Modal title={`Detection zone · ${camera?.name || ''}`} open={Boolean(camera)} onClose={onClose} drawer><div className="zone-editor">
    <p>Click the image to add normalized points. Two points make a line; three or more make a polygon. Points stay aligned as the image resizes.</p>
    {snapshot.loading ? <Loader label="Loading camera snapshot" /> : snapshot.error ? <ErrorBox error={snapshot.error} onRetry={snapshot.reload} /> : !snapshotUrl ? <EmptyState title="No snapshot available" description="Configure a readable source before editing the zone." /> : <div className="zone-image" style={{ aspectRatio }} onClick={clickPoint} role="button" tabIndex={0} aria-label="Click to add zone points" onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') setPoints((value) => [...value, [0.5, 0.5]]) }}><img src={snapshotUrl} alt={`Snapshot from ${camera.name}`} onLoad={(event) => { const image = event.currentTarget; if (image.naturalWidth && image.naturalHeight) setAspectRatio(image.naturalWidth / image.naturalHeight) }} /><svg viewBox="0 0 1 1" preserveAspectRatio="none" aria-label="Normalized zone overlay">{isPolygon ? <polygon points={points.map(([x, y]) => `${x},${y}`).join(' ')} /> : points.length === 2 ? <line x1={points[0][0]} y1={points[0][1]} x2={points[1][0]} y2={points[1][1]} /> : null}{points.map(([x, y], index) => <circle key={`${x}-${y}-${index}`} cx={x} cy={y} r=".012" />)}</svg></div>}
    <div className="zone-toolbar"><span>{points.length} points · {points.length === 2 ? 'Line' : points.length >= 3 ? 'Polygon' : 'Add at least 2'}</span><div className="button-row"><button className="button button-secondary" type="button" onClick={() => setPoints((value) => value.slice(0, -1))} disabled={!points.length}>Undo</button><button className="button button-secondary" type="button" onClick={() => setPoints([])} disabled={!points.length}>Clear</button><button className="button button-primary" type="button" onClick={save} disabled={points.length < 2 || points.length === 1 || saving || snapshot.loading || Boolean(snapshot.error)}>{saving ? 'Saving…' : 'Save zone'}</button></div></div>
    {saveError && <ErrorBox error={saveError} onRetry={save} />}
  </div></Modal>
}
