import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { listCameras, listViolations } from '../api/index.js'
import { useApiData } from '../hooks/useApiData.js'
import { useLiveAlerts } from '../context/LiveAlertsContext.jsx'
import { formatDate, formatPercent } from '../utils/format.js'
import Badge from '../components/common/Badge.jsx'
import DataTable from '../components/common/DataTable.jsx'
import EvidenceImage from '../components/common/EvidenceImage.jsx'
import FilterBar from '../components/common/FilterBar.jsx'
import PageIntro from '../components/common/PageIntro.jsx'
import Pagination from '../components/common/Pagination.jsx'
import Panel from '../components/common/Panel.jsx'
import ViolationDetailDrawer from './ViolationDetailDrawer.jsx'
import { updateViolationFilter } from '../utils/violationFilters.js'

const PAGE_SIZE = 10
const localBoundary = (day, end = false) => {
  if (!day) return undefined
  const [year, month, date] = day.split('-').map(Number)
  return new Date(year, month - 1, date, end ? 23 : 0, end ? 59 : 0, end ? 59 : 0, end ? 999 : 0).toISOString()
}

export default function ViolationsPage() {
  const [params, setParams] = useSearchParams()
  const [searchDraft, setSearchDraft] = useState(params.get('track_id') || '')
  const type = params.get('type') || ''
  const result = params.get('result') || ''
  const camera = params.get('camera') || ''
  const reviewStatus = params.get('review_status') || ''
  const dateFrom = params.get('date_from') || ''
  const dateTo = params.get('date_to') || ''
  const trackId = params.get('track_id') || ''
  const page = Math.max(1, Number(params.get('page') || 1))
  const loadCameras = useCallback(() => listCameras(), [])
  const cameras = useApiData(loadCameras)
  const loadViolations = useCallback(async () => {
    const base = { type, camera, date_from: localBoundary(dateFrom), date_to: localBoundary(dateTo, true), track_id: trackId ? Number(trackId) : undefined, review_status: reviewStatus || undefined, page: 1, limit: 500 }
    if (result === 'needs_review') return listViolations({ ...base, result: 'unclear' })
    if (result === 'violation') {
      const [helmet, seatbelt] = await Promise.all([listViolations({ ...base, result: 'no_helmet' }), listViolations({ ...base, result: 'no_seatbelt' })])
      const items = [...helmet.items, ...seatbelt.items].sort((a, b) => b.created_at.localeCompare(a.created_at))
      return { items, total: helmet.total + seatbelt.total, page: 1, limit: 500 }
    }
    return listViolations(base)
  }, [type, camera, dateFrom, dateTo, trackId, reviewStatus, result])
  const data = useApiData(loadViolations)
  const { alerts: socketAlerts } = useLiveAlerts()

  const updateParam = useCallback((key, value, resetPage = true) => {
    if ((params.get(key) || '') === value) return
    const next = updateViolationFilter(params, key, value, resetPage)
    setParams(next, { replace: true })
  }, [params, setParams])
  useEffect(() => {
    const timeout = window.setTimeout(() => updateParam('track_id', searchDraft.trim()), 350)
    return () => window.clearTimeout(timeout)
  }, [searchDraft, updateParam])
  const selected = useMemo(() => {
    const id = params.get('event_id')
    return id ? data.data?.items.find((item) => item.event_id === id) || null : null
  }, [params, data.data])
  const filtered = useMemo(() => {
    const live = (socketAlerts || []).filter((item) => {
      if (type && item.violation_type !== type) return false
      if (camera && item.camera_id !== camera) return false
      if (trackId && String(item.track_id) !== trackId) return false
      if (result === 'needs_review' && !item.provisional && item.ai_result !== 'unclear') return false
      if (result === 'violation' && (item.provisional || item.ai_result === 'unclear')) return false
      return true
    })
    return [...new Map([...live, ...(data.data?.items || [])].map((item) => [item.event_id, item])).values()].sort((a, b) => b.created_at.localeCompare(a.created_at))
  }, [data.data, socketAlerts, type, camera, trackId, result])
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const rows = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
  const closeDrawer = () => updateParam('event_id', '', false)
  const updateReviewed = (updated) => {
    data.setData((current) => current && ({ ...current, items: current.items.map((item) => item.event_id === updated.event_id ? { ...item, ...updated, review_history: [...(item.review_history || []), { reviewed_by: updated.reviewed_by, reviewed_at: updated.reviewed_at, final_decision: updated.final_decision, review_note: updated.review_note }] } : item) }))
    data.reload()
  }
  const columns = [
    { key: 'evidence', label: 'Evidence', render: (_, row) => <EvidenceImage path={row.evidence?.composite} alt={`Evidence ${row.event_id}`} className="table-thumb" /> },
    { key: 'event_id', label: 'Event ID', render: (value) => <span className="mono-text">{value}</span> },
    { key: 'track_id', label: 'Track ID' },
    { key: 'violation_type', label: 'Type', render: (value) => <span className="capitalize">{value}</span> },
    { key: 'camera_id', label: 'Camera' },
    { key: 'created_at', label: 'Time', render: (value) => formatDate(value) },
    { key: 'detection_confidence', label: 'Confidence', render: (value) => formatPercent(value * 100) },
    { key: 'review_status', label: 'Review status', render: (value, row) => <Badge value={row.ai_result === 'unclear' ? 'NEEDS_REVIEW' : value} /> },
  ]

  return <div className="page-stack">
    <PageIntro title="Violation management" description="Find events, inspect evidence and review uncertain detections." />
    <Panel>
      <FilterBar onReset={() => { setSearchDraft(''); setParams(new URLSearchParams()) }}>
        <label className="filter-field">Type<select value={type} onChange={(event) => updateParam('type', event.target.value)}><option value="">All types</option><option value="helmet">Helmet</option><option value="seatbelt">Seatbelt</option></select></label>
        <label className="filter-field">Result<select value={result} onChange={(event) => updateParam('result', event.target.value)}><option value="">All results</option><option value="violation">Violation</option><option value="needs_review">Needs review</option></select></label>
        <label className="filter-field">Camera<select value={camera} onChange={(event) => updateParam('camera', event.target.value)}><option value="">All cameras</option>{cameras.data?.map((item) => <option value={item.camera_id} key={item.camera_id}>{item.name}</option>)}</select></label>
        <label className="filter-field">From<input type="date" value={dateFrom} onChange={(event) => updateParam('date_from', event.target.value)} /></label>
        <label className="filter-field">To<input type="date" value={dateTo} onChange={(event) => updateParam('date_to', event.target.value)} /></label>
        <label className="filter-field">Review status<select value={reviewStatus} onChange={(event) => updateParam('review_status', event.target.value)}><option value="">Any status</option><option value="UNREVIEWED">Pending / not reviewed</option><option value="REVIEWED">Reviewed</option></select></label>
        <label className="filter-field">Track ID<input type="search" inputMode="numeric" value={searchDraft} placeholder="Search tracking ID" onChange={(event) => setSearchDraft(event.target.value.replace(/\D/g, ''))} /></label>
      </FilterBar>
      {cameras.error && <div className="inline-state"><span>Camera filter could not load.</span><button className="text-button" type="button" onClick={cameras.reload}>Retry</button></div>}
    </Panel>
    <Panel title="Violation events" subtitle={`${data.data?.total ?? 0} matching events · filter state is saved in this page URL`}>
      <DataTable columns={columns} rows={rows} rowKey="event_id" loading={data.loading} error={data.error} onRetry={data.reload} emptyTitle="No matching violations" emptyDescription="Try changing or clearing your filters." onRowClick={(item) => updateParam('event_id', item.event_id, false)} />
      {!data.loading && !data.error && <Pagination page={page} pages={pages} onChange={(value) => updateParam('page', String(value), false)} />}
      {!data.loading && !data.error && data.data?.total > filtered.length && <p className="chart-summary">Showing the first {filtered.length} of {data.data.total} events. Refine filters to reach older events within the backend page limit.</p>}
    </Panel>
    <ViolationDetailDrawer selected={selected} onClose={closeDrawer} onReviewed={updateReviewed} />
  </div>
}
