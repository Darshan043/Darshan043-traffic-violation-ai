import { useCallback, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Activity, AlertTriangle, CheckCircle2, Users } from 'lucide-react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { listCameras, listViolations, statsDaily, statsSummary } from '../api/index.js'
import Badge from '../components/common/Badge.jsx'
import EmptyState from '../components/common/EmptyState.jsx'
import ErrorBox from '../components/common/ErrorBox.jsx'
import EvidenceImage from '../components/common/EvidenceImage.jsx'
import Loader from '../components/common/Loader.jsx'
import PageIntro from '../components/common/PageIntro.jsx'
import Panel from '../components/common/Panel.jsx'
import StatCard from '../components/common/StatCard.jsx'
import LiveCanvas from '../components/live/LiveCanvas.jsx'
import { useApiData } from '../hooks/useApiData.js'
import { useLiveAlerts } from '../context/LiveAlertsContext.jsx'
import { formatDate, formatPercent } from '../utils/format.js'

export default function DashboardPage() {
  const [cameraId, setCameraId] = useState('')
  const [range, setRange] = useState(7)
  const loadSummary = useCallback(() => statsSummary(), [])
  const loadCameras = useCallback(() => listCameras(), [])
  const loadDaily = useCallback(() => statsDaily(), [])
  const loadViolations = useCallback(() => listViolations({ page: 1, limit: 50 }), [])
  const summary = useApiData(loadSummary)
  const cameras = useApiData(loadCameras)
  const daily = useApiData(loadDaily)
  const violations = useApiData(loadViolations)
  const { alerts: socketAlerts } = useLiveAlerts()
  const selected = cameras.data?.find((camera) => camera.camera_id === cameraId) || cameras.data?.[0]
  const chartRows = useMemo(() => (daily.data || []).slice(0, range).toReversed().map((item) => ({ ...item, day: item.date.slice(5) })), [daily.data, range])
  const newest = useMemo(() => [...new Map([...(socketAlerts || []), ...(violations.data?.items || [])].map((item) => [item.event_id, item])).values()].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 50), [socketAlerts, violations.data])

  return <div className="page-stack">
    <PageIntro title="Traffic overview" description="A live summary of camera activity and road safety events." action={<span className="updated-label"><Activity size={15} /> Mock-first monitoring</span>} />
    <section className="stats-grid" aria-label="Traffic statistics">
      {summary.loading ? <Loader label="Loading summary" /> : summary.error ? <ErrorBox error={summary.error} onRetry={summary.reload} /> : summary.data ? <>
        <StatCard label="Total vehicles" value={summary.data.total_vehicles.toLocaleString()} hint="All processed events" icon={Users} />
        <StatCard label="Total violations" value={summary.data.violations.toLocaleString()} hint={`${summary.data.needs_review} need review`} icon={AlertTriangle} />
        <StatCard label="Helmet compliance" value={formatPercent(summary.data.helmet_compliance_percentage)} hint="Confirmed outcomes only" icon={CheckCircle2} />
        <StatCard label="Seatbelt compliance" value={formatPercent(summary.data.seatbelt_compliance_percentage)} hint="Confirmed outcomes only" icon={CheckCircle2} />
      </> : <EmptyState title="No summary data" />}
    </section>
    <div className="dashboard-grid">
      <Panel title="Live camera preview" subtitle="Animated placeholder in mock mode" action={cameras.data?.length > 0 && <select className="compact-select" aria-label="Preview camera" value={selected?.camera_id || ''} onChange={(event) => setCameraId(event.target.value)}>{cameras.data.map((camera) => <option key={camera.camera_id} value={camera.camera_id}>{camera.name}</option>)}</select>} className="preview-panel">
        {cameras.loading ? <Loader label="Loading cameras" /> : cameras.error ? <ErrorBox error={cameras.error} onRetry={cameras.reload} /> : selected ? <><div className="preview-canvas-wrap"><LiveCanvas cameraName={selected.name} /><div className="preview-live"><span className="status-indicator status-green" /> LIVE MOCK</div></div><div className="preview-meta"><span>{selected.location}</span><Badge value={selected.status} /></div></> : <EmptyState title="No cameras configured" description="Add a camera to see a preview here." />}
      </Panel>
      <Panel title="Live alerts" subtitle="Newest first · up to 50 alerts" action={<Link className="text-link" to="/violations">View all</Link>} className="alerts-panel">
        {violations.loading ? <Loader label="Loading alerts" /> : violations.error ? <ErrorBox error={violations.error} onRetry={violations.reload} /> : newest.length ? <div className="alert-list">{newest.slice(0, 50).map((item) => <Link className="alert-row" to={`/violations?event_id=${encodeURIComponent(item.event_id)}`} key={item.event_id}><span className={`alert-symbol ${item.ai_result === 'unclear' ? 'alert-amber' : ''}`}><AlertTriangle size={14} /></span><span className="alert-copy"><strong>{item.ai_result === 'unclear' ? 'Needs review' : `No ${item.violation_type}`}</strong><small>{item.camera_id} · Track {item.track_id}</small></span><time>{formatDate(item.created_at, { dateStyle: 'short', timeStyle: 'short' })}</time></Link>)}</div> : <EmptyState title="No recent alerts" description="New events will appear here." />}
      </Panel>
    </div>
    <div className="dashboard-grid dashboard-grid-bottom">
      <Panel title="Daily violations" subtitle={`Last ${range} days`} action={<div className="range-toggle"><button className={range === 7 ? 'selected' : ''} onClick={() => setRange(7)} type="button">7 days</button><button className={range === 30 ? 'selected' : ''} onClick={() => setRange(30)} type="button">30 days</button></div>}>
        {daily.loading ? <Loader label="Loading daily chart" /> : daily.error ? <ErrorBox error={daily.error} onRetry={daily.reload} /> : chartRows.length ? <><div className="chart-frame chart-short"><ResponsiveContainer width="100%" height="100%"><LineChart data={chartRows} margin={{ top: 10, right: 12, left: -20, bottom: 0 }}><CartesianGrid stroke="#edf1f3" vertical={false} /><XAxis dataKey="day" tickLine={false} axisLine={false} fontSize={10} /><YAxis allowDecimals={false} tickLine={false} axisLine={false} fontSize={10} /><Tooltip /><Line dataKey="violations" name="Violations" stroke="#d4575d" strokeWidth={2.5} dot={false} activeDot={{ r: 4 }} /></LineChart></ResponsiveContainer></div><p className="chart-summary">Daily violation counts over the selected period. Review-needed events are tracked separately.</p></> : <EmptyState title="No daily data" />}
      </Panel>
      <Panel title="Latest violations" subtitle="Most recent 10 events" action={<Link className="text-link" to="/violations">Open table</Link>}>
        {violations.loading ? <Loader label="Loading violations" /> : violations.error ? <ErrorBox error={violations.error} onRetry={violations.reload} /> : newest.length ? <div className="latest-list">{newest.slice(0, 10).map((item) => <Link to={`/violations?event_id=${encodeURIComponent(item.event_id)}`} key={item.event_id} className="latest-row"><EvidenceImage path={item.evidence?.composite} alt={`Evidence for ${item.event_id}`} className="latest-thumb" /><span><strong>{item.ai_result === 'unclear' ? 'Needs review' : `No ${item.violation_type}`}</strong><small>{item.camera_id} · Track {item.track_id} · {formatDate(item.created_at, { dateStyle: 'short', timeStyle: 'short' })}</small></span><Badge value={item.ai_result === 'unclear' ? 'NEEDS_REVIEW' : item.violation_type === 'helmet' ? 'NO_HELMET' : 'NO_SEATBELT'} /></Link>)}</div> : <EmptyState title="No violations recorded" />}
      </Panel>
    </div>
  </div>
}
