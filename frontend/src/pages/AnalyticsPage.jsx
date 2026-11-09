import { useCallback, useMemo, useState } from 'react'
import { Download } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { exportViolationsCsv, listCameras, statsCameras, statsDaily, statsSummary } from '../api/index.js'
import { useAuth } from '../context/AuthContext.jsx'
import { can } from '../context/permissions.js'
import { useToast } from '../context/ToastContext.jsx'
import { useApiData } from '../hooks/useApiData.js'
import { formatPercent } from '../utils/format.js'
import DataTable from '../components/common/DataTable.jsx'
import EmptyState from '../components/common/EmptyState.jsx'
import ErrorBox from '../components/common/ErrorBox.jsx'
import PageIntro from '../components/common/PageIntro.jsx'
import Panel from '../components/common/Panel.jsx'

const COLORS = ['#18966c', '#d4565d', '#e4a33e', '#7f8f9a']
const dayKey = (date) => date.toISOString().slice(0, 10)
const localStart = (day) => { if (!day) return undefined; const [y, m, d] = day.split('-').map(Number); return new Date(y, m - 1, d).toISOString() }
const localEnd = (day) => { if (!day) return undefined; const [y, m, d] = day.split('-').map(Number); return new Date(y, m - 1, d, 23, 59, 59, 999).toISOString() }

export default function AnalyticsPage() {
  const { user } = useAuth()
  const toast = useToast()
  const loadDaily = useCallback(() => statsDaily(), [])
  const loadCameras = useCallback(() => statsCameras(), [])
  const loadSummary = useCallback(() => statsSummary(), [])
  const loadCameraList = useCallback(() => listCameras(), [])
  const daily = useApiData(loadDaily)
  const cameraStats = useApiData(loadCameras)
  const summary = useApiData(loadSummary)
  const cameras = useApiData(loadCameraList)
  const [preset, setPreset] = useState('30')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [granularity, setGranularity] = useState('day')
  const [camera, setCamera] = useState('')
  const [type, setType] = useState('')
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState(null)

  const bounds = useMemo(() => {
    const end = new Date()
    const start = new Date(end)
    if (preset === 'today') start.setHours(0, 0, 0, 0)
    else if (preset === '7') start.setDate(end.getDate() - 6)
    else if (preset === '30') start.setDate(end.getDate() - 29)
    else return { from, to }
    return { from: dayKey(start), to: dayKey(end) }
  }, [preset, from, to])
  const scopedDaily = useMemo(() => {
    const rows = (daily.data || []).filter((item) => (!bounds.from || item.date >= bounds.from) && (!bounds.to || item.date <= bounds.to))
    if (granularity === 'day') return rows.toReversed().map((item) => ({ label: item.date.slice(5), violations: item.violations, needs_review: item.needs_review }))
    const grouped = new Map()
    rows.forEach((item) => {
      const date = new Date(`${item.date}T00:00:00`)
      let label
      if (granularity === 'week') {
        const week = new Date(date); week.setDate(date.getDate() - ((date.getDay() + 6) % 7)); label = dayKey(week)
      } else label = item.date.slice(0, 7)
      const group = grouped.get(label) || { label, violations: 0, needs_review: 0 }
      group.violations += item.violations; group.needs_review += item.needs_review; grouped.set(label, group)
    })
    return [...grouped.values()].sort((a, b) => a.label.localeCompare(b.label))
  }, [daily.data, bounds, granularity])
  const lineSummary = scopedDaily.length ? `${scopedDaily.length} ${granularity === 'day' ? 'days' : granularity === 'week' ? 'weeks' : 'months'} shown; ${scopedDaily.reduce((sum, row) => sum + row.violations, 0)} confirmed violations and ${scopedDaily.reduce((sum, row) => sum + row.needs_review, 0)} review events.` : 'No daily values for this date range.'
  const complianceRows = summary.data ? [{ name: 'Helmet', compliant: summary.data.helmet_compliance_percentage, violations: 100 - summary.data.helmet_compliance_percentage }, { name: 'Seatbelt', compliant: summary.data.seatbelt_compliance_percentage, violations: 100 - summary.data.seatbelt_compliance_percentage }] : []
  const cameraRows = (cameraStats.data || []).filter((row) => !camera || row.camera_id === camera).map((row) => ({ ...row, review_rate: row.total_vehicles ? (row.needs_review / row.total_vehicles) * 100 : 0 }))
  const mixRows = summary.data ? [{ name: 'Compliant', value: summary.data.compliant_vehicles }, { name: 'Violation', value: summary.data.violations }, { name: 'Needs review', value: summary.data.needs_review }] : []

  const doExport = async () => {
    if (!can(user?.role, 'export')) return
    setExporting(true); setExportError(null)
    try {
      const blob = await exportViolationsCsv({ type: type || undefined, camera: camera || undefined, date_from: localStart(bounds.from), date_to: localEnd(bounds.to) })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'violations.csv'; anchor.click(); URL.revokeObjectURL(url)
      toast('CSV export downloaded.', 'success')
    } catch (error) { setExportError(error) }
    finally { setExporting(false) }
  }

  return <div className="page-stack">
    <PageIntro title="Analytics & reports" description="Trend, compare and export traffic violation data." action={<button className="button button-primary" type="button" onClick={doExport} disabled={!can(user?.role, 'export') || exporting}><Download size={15} />{exporting ? 'Preparing…' : 'Export CSV'}</button>} />
    <Panel title="Report filters" subtitle="Charts use the full stats endpoints; date selection filters daily trends in the browser.">
      <div className="report-filters"><label className="filter-field">Date range<select value={preset} onChange={(event) => setPreset(event.target.value)}><option value="today">Today</option><option value="7">Last 7 days</option><option value="30">Last 30 days</option><option value="custom">Custom</option></select></label>{preset === 'custom' && <><label className="filter-field">From<input type="date" value={from} onChange={(event) => setFrom(event.target.value)} /></label><label className="filter-field">To<input type="date" value={to} onChange={(event) => setTo(event.target.value)} /></label></>}<label className="filter-field">Camera<select value={camera} onChange={(event) => setCamera(event.target.value)}><option value="">All cameras</option>{cameras.data?.map((item) => <option key={item.camera_id} value={item.camera_id}>{item.name}</option>)}</select></label><label className="filter-field">Violation type<select value={type} onChange={(event) => setType(event.target.value)}><option value="">Helmet & seatbelt</option><option value="helmet">Helmet</option><option value="seatbelt">Seatbelt</option></select></label><label className="filter-field">Trend unit<select value={granularity} onChange={(event) => setGranularity(event.target.value)}><option value="day">Daily</option><option value="week">Weekly</option><option value="month">Monthly</option></select></label></div>
      {exportError && <ErrorBox error={exportError} onRetry={doExport} />}{!can(user?.role, 'export') && <p className="permission-note">CSV export is available to administrators and reviewers.</p>}
    </Panel>
    <div className="analytics-chart-grid">
      <Panel title="Violation trend" subtitle="Counts by selected time unit">
        {daily.loading ? <div className="chart-load"><span className="spinner" /> Loading daily stats…</div> : daily.error ? <ErrorBox error={daily.error} onRetry={daily.reload} /> : scopedDaily.length ? <><div className="chart-frame"><ResponsiveContainer width="100%" height="100%"><LineChart data={scopedDaily} margin={{ top: 12, right: 12, left: -20, bottom: 0 }}><CartesianGrid stroke="#edf1f3" vertical={false} /><XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={9} /><YAxis allowDecimals={false} tickLine={false} axisLine={false} fontSize={10} /><Tooltip /><Legend /><Line dataKey="violations" name="Violations" stroke="#d4575d" strokeWidth={2.4} dot={false} /><Line dataKey="needs_review" name="Needs review" stroke="#e0a03a" strokeWidth={2} dot={false} /></LineChart></ResponsiveContainer></div><p className="chart-summary">{lineSummary}</p></> : <EmptyState title="No trend data" description={lineSummary} />}
      </Panel>
      <Panel title="Helmet & seatbelt compliance" subtitle="Confirmed outcome rates">
        {summary.loading ? <div className="chart-load"><span className="spinner" /> Loading summary…</div> : summary.error ? <ErrorBox error={summary.error} onRetry={summary.reload} /> : complianceRows.length ? <><div className="chart-frame"><ResponsiveContainer width="100%" height="100%"><BarChart data={complianceRows} margin={{ top: 10, right: 10, left: -18, bottom: 0 }}><CartesianGrid stroke="#edf1f3" vertical={false} /><XAxis dataKey="name" tickLine={false} axisLine={false} fontSize={10} /><YAxis domain={[0, 100]} tickFormatter={(value) => `${value}%`} tickLine={false} axisLine={false} fontSize={9} /><Tooltip formatter={(value) => `${Number(value).toFixed(1)}%`} /><Legend /><Bar dataKey="compliant" name="Compliant" fill="#19966c" radius={[4, 4, 0, 0]} /><Bar dataKey="violations" name="Violations" fill="#d4575d" radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer></div><p className="chart-summary">Helmet {formatPercent(summary.data.helmet_compliance_percentage)} · Seatbelt {formatPercent(summary.data.seatbelt_compliance_percentage)}. Review-needed events are excluded.</p></> : <EmptyState title="No compliance data" />}
      </Panel>
      <Panel title="Events by camera" subtitle="Vehicle events in the available stats">
        {cameraStats.loading ? <div className="chart-load"><span className="spinner" /> Loading camera stats…</div> : cameraStats.error ? <ErrorBox error={cameraStats.error} onRetry={cameraStats.reload} /> : cameraRows.length ? <><div className="chart-frame"><ResponsiveContainer width="100%" height="100%"><BarChart data={cameraRows} margin={{ top: 10, right: 10, left: -18, bottom: 5 }}><CartesianGrid stroke="#edf1f3" vertical={false} /><XAxis dataKey="camera_name" tickLine={false} axisLine={false} fontSize={9} /><YAxis allowDecimals={false} tickLine={false} axisLine={false} fontSize={9} /><Tooltip /><Legend /><Bar dataKey="violations" name="Violations" fill="#d4575d" radius={[4, 4, 0, 0]} /><Bar dataKey="compliant_vehicles" name="Compliant" fill="#19966c" radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer></div><p className="chart-summary">{cameraRows.map((row) => `${row.camera_name}: ${row.total_vehicles} events`).join(' · ')}</p></> : <EmptyState title="No camera statistics" />}
      </Panel>
      <Panel title="Result mix" subtitle="All currently available events">
        {summary.loading ? <div className="chart-load"><span className="spinner" /> Loading result mix…</div> : summary.error ? <ErrorBox error={summary.error} onRetry={summary.reload} /> : mixRows.length ? <><div className="chart-frame donut-frame"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={mixRows} dataKey="value" nameKey="name" innerRadius={55} outerRadius={87} paddingAngle={3}>{mixRows.map((_, index) => <Cell key={index} fill={COLORS[index]} />)}</Pie><Tooltip /><Legend /></PieChart></ResponsiveContainer></div><p className="chart-summary">Compliant {summary.data.compliant_vehicles} · Violations {summary.data.violations} · Needs review {summary.data.needs_review}. This chart covers all dates.</p></> : <EmptyState title="No result data" />}
      </Panel>
    </div>
    <Panel title="Camera performance" subtitle="Events, violation count and review rate">
      <DataTable loading={cameraStats.loading} error={cameraStats.error} onRetry={cameraStats.reload} rows={cameraRows} rowKey="camera_id" emptyTitle="No camera performance data" columns={[{ key: 'camera_name', label: 'Camera' }, { key: 'total_vehicles', label: 'Events' }, { key: 'violations', label: 'Violations' }, { key: 'review_rate', label: 'Review rate', render: (value) => formatPercent(value) }, { key: 'compliance_percentage', label: 'Compliance', render: (value) => formatPercent(value) }]} />
    </Panel>
    {cameras.error && <Panel title="Camera filter"><ErrorBox error={cameras.error} onRetry={cameras.reload} /></Panel>}
  </div>
}
