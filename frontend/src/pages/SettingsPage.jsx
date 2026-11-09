import { useCallback, useState } from 'react'
import { Check, Database, Plus, RefreshCw, ShieldCheck, Users } from 'lucide-react'
import { createUser, disableUser, getSettings, health, listUsers, putSettings, updateUser } from '../api/index.js'
import { useAuth } from '../context/AuthContext.jsx'
import { can } from '../context/permissions.js'
import { useToast } from '../context/ToastContext.jsx'
import { useApiData } from '../hooks/useApiData.js'
import { formatDate } from '../utils/format.js'
import Badge from '../components/common/Badge.jsx'
import ConfirmDialog from '../components/common/ConfirmDialog.jsx'
import DataTable from '../components/common/DataTable.jsx'
import EmptyState from '../components/common/EmptyState.jsx'
import ErrorBox from '../components/common/ErrorBox.jsx'
import Modal from '../components/common/Modal.jsx'
import PageIntro from '../components/common/PageIntro.jsx'
import Panel from '../components/common/Panel.jsx'

const defaultSettings = { helmet_min_confidence: 0.4, seatbelt_min_confidence: 0.4, seatbelt_min_car_height: 120, duplicate_window_sec: 2, duplicate_iou_threshold: 0.5, max_workers: 1, frame_skip: 1, image_size: 640, evidence_retention_days: 30, extra: {} }
const thresholdFields = [
  ['observation_min_conf', 0.4, 'Minimum confidence needed before an observation is counted. Engine has a related default; no settings API field exists.'],
  ['min_observations', 3, 'Minimum frames needed before the engine decides. Engine default shown; no settings API field exists.'],
  ['compliant_threshold', 0.55, 'Vote share needed to mark an event compliant. Engine default shown; no settings API field exists.'],
  ['violation_threshold', 0.7, 'Vote share needed to confirm a violation. Engine default shown; no settings API field exists.'],
  ['agreement_ratio', null, 'Minimum agreement between observations. Backend does not provide a matching setting.'],
  ['max_unclear_ratio', null, 'Maximum unclear share before review is requested. Backend does not provide a matching setting.'],
]

export default function SettingsPage() {
  const { user } = useAuth()
  const toast = useToast()
  const admin = can(user?.role, 'manage_users')
  const [tab, setTab] = useState('users')
  const [settingsForm, setSettingsForm] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState(null)
  const [userModal, setUserModal] = useState(false)
  const [newUser, setNewUser] = useState({ username: '', password: '', role: 'viewer' })
  const [userError, setUserError] = useState(null)
  const [disableTarget, setDisableTarget] = useState(null)

  const loadUsers = useCallback(() => admin ? listUsers() : Promise.resolve([]), [admin])
  const loadSettings = useCallback(() => admin ? getSettings() : Promise.resolve(null), [admin])
  const loadHealth = useCallback(() => health(), [])
  const users = useApiData(loadUsers)
  const settings = useApiData(loadSettings)
  const systemHealth = useApiData(loadHealth)
  const saveSettings = async (event) => {
    event.preventDefault()
    const current = settingsForm || settings.data || defaultSettings
    const integerFields = ['frame_skip', 'image_size', 'evidence_retention_days', 'max_workers']
    if (current.frame_skip < 1 || current.evidence_retention_days < 1 || current.max_workers < 1 || integerFields.some((key) => !Number.isInteger(Number(current[key])))) { setSaveError(new Error('Frame skip, image size, workers and retention days must use valid whole numbers.')); return }
    setSaving(true); setSaveError(null)
    try { const saved = await putSettings(current); setSettingsForm(saved); toast('System settings saved.', 'success'); settings.reload() }
    catch (error) { setSaveError(error) }
    finally { setSaving(false) }
  }
  const saveNewUser = async (event) => {
    event.preventDefault(); setUserError(null)
    if (newUser.username.length < 3 || newUser.username.length > 50 || newUser.password.length < 6) { setUserError(new Error('User names need 3â€“50 characters and passwords need at least 6.')); return }
    try { await createUser(newUser); users.reload(); setUserModal(false); setNewUser({ username: '', password: '', role: 'viewer' }); toast('User created.', 'success') }
    catch (error) { setUserError(error) }
  }
  const setNumber = (key, value) => setSettingsForm((current) => ({ ...(current || settings.data || defaultSettings), [key]: value === '' ? '' : Number(value) }))
  const changeRole = async (person, role) => {
    try { await updateUser(person.id, { role }); users.reload(); toast(`Role updated for ${person.username}.`, 'success') }
    catch (error) { setUserError(error) }
  }
  const toggleActive = async (person) => {
    try { if (person.is_active) await disableUser(person.id); else await updateUser(person.id, { is_active: true }); users.reload(); setDisableTarget(null); toast(`User ${person.is_active ? 'disabled' : 'enabled'}.`, 'success') }
    catch (error) { setUserError(error) }
  }
  const userColumns = [
    { key: 'username', label: 'User', render: (value) => <strong>{value}</strong> },
    { key: 'role', label: 'Role', render: (value, person) => admin ? <select className="role-select" value={value} onChange={(event) => changeRole(person, event.target.value)} aria-label={`Role for ${person.username}`}><option value="admin">Admin</option><option value="reviewer">Reviewer</option><option value="viewer">Viewer</option></select> : <span className="capitalize">{value}</span> },
    { key: 'is_active', label: 'Status', render: (value) => <Badge value={value ? 'online' : 'offline'} label={value ? 'Active' : 'Disabled'} /> },
    { key: 'created_at', label: 'Created', render: (value) => formatDate(value, { dateStyle: 'medium', timeStyle: undefined }) },
    { key: 'actions', label: 'Actions', render: (_, person) => admin && <button className={`button button-small ${person.is_active ? 'button-secondary' : 'button-primary'}`} type="button" disabled={person.id === user?.id && person.is_active} onClick={() => person.is_active ? setDisableTarget(person) : toggleActive(person)}>{person.is_active ? 'Disable' : 'Enable'}</button> },
  ]

  return <div className="page-stack">
    <PageIntro title="Settings & administration" description="Manage access and review system configuration." />
    <div className="settings-tabs" role="tablist" aria-label="Settings sections">{[['users', Users, 'Users'], ['detection', ShieldCheck, 'Detection'], ['system', RefreshCw, 'System'], ['storage', Database, 'Storage & database']].map(([key, Icon, label]) => <button role="tab" aria-selected={tab === key} className={tab === key ? 'settings-tab active' : 'settings-tab'} key={key} type="button" onClick={() => setTab(key)}><Icon size={15} />{label}</button>)}</div>
    {tab === 'users' && <Panel title="User accounts" subtitle="Admins can create users, change roles and disable accounts." action={admin && <button className="button button-primary button-small" type="button" onClick={() => { setUserError(null); setUserModal(true) }}><Plus size={14} />Add user</button>}>
      {admin ? <><DataTable columns={userColumns} rows={users.data || []} rowKey="id" loading={users.loading} error={users.error} onRetry={users.reload} emptyTitle="No users found" emptyDescription="Add a user account to get started." />{userError && <ErrorBox error={userError} onRetry={() => { setUserError(null); users.reload() }} />}</> : <div className="settings-unavailable"><ShieldCheck size={19} /><strong>User administration is restricted</strong><span>Only administrators can list or change accounts.</span></div>}
    </Panel>}
    {tab === 'detection' && <Panel title="Detection decision thresholds" subtitle="These values describe the engine decision rules, but the settings API does not expose them yet."><div className="threshold-list">{thresholdFields.map(([key, value, help]) => <div className="threshold-row" key={key}><label htmlFor={`threshold-${key}`}>{key.replaceAll('_', ' ')}</label><input id={`threshold-${key}`} className="field-input" disabled value={value === null ? '' : value} placeholder="Not available yet" type="number" min="0" max="1" step="0.01" /><p>{help}</p><span className="not-available">Not available yet</span></div>)}</div><div className="threshold-footer"><span>Backend API support is needed before these controls can be changed.</span><button className="button button-secondary" type="button" disabled>Reset to default</button></div></Panel>}
    {tab === 'system' && <Panel title="System settings" subtitle="Frame processing and evidence retention values from the backend settings API.">{!admin ? <div className="settings-unavailable"><ShieldCheck size={19} /><strong>Admin access is required to read settings.</strong><span>The backend protects this endpoint.</span></div> : settings.loading ? <div className="chart-load"><span className="spinner" /> Loading settingsâ€¦</div> : settings.error ? <ErrorBox error={settings.error} onRetry={settings.reload} /> : settings.data && <form className="settings-form" onSubmit={saveSettings}><div className="settings-field-grid">{[['frame_skip', 'Frame skip', 1, 120, 1, 'Process every Nth frame.'], ['image_size', 'Image size', 320, 1280, 32, 'Inference image dimension in pixels.'], ['evidence_retention_days', 'Evidence retention (days)', 1, 3650, 1, 'How long evidence files should be kept.'], ['max_workers', 'Maximum workers', 1, 8, 1, 'Maximum simultaneous processing workers.']].map(([key, label, min, max, step, help]) => <label className="form-label" key={key}>{label}<input className="field-input" type="number" min={min} max={max} step={step} required value={settingsForm?.[key] ?? settings.data[key]} onChange={(event) => setNumber(key, event.target.value)} /><small>{help}</small></label>)}</div><div className="settings-supported-note"><Check size={15} />Values are saved through the backend settings endpoint.</div>{saveError && <ErrorBox error={saveError} onRetry={() => setSaveError(null)} />}<div className="button-row"><button className="button button-secondary" type="button" onClick={() => setSettingsForm(defaultSettings)}>Reset to default</button><button className="button button-primary" disabled={saving}>{saving ? 'Savingâ€¦' : 'Save settings'}</button></div></form>}</Panel>}
    {tab === 'storage' && <div className="page-stack"><Panel title="Backend health" subtitle="Public liveness check; no credentials or secrets are shown.">{systemHealth.loading ? <div className="chart-load"><span className="spinner" /> Checking healthâ€¦</div> : systemHealth.error ? <ErrorBox error={systemHealth.error} onRetry={systemHealth.reload} /> : systemHealth.data ? <div className="health-card"><span className="health-icon"><Check size={17} /></span><div><strong>Service status: {systemHealth.data.status}</strong><small>The backend health endpoint confirms that the API is responding.</small></div></div> : <EmptyState title="No health data" />}</Panel><Panel title="Storage and database status" subtitle="Read-only service details."><div className="settings-unavailable"><Database size={20} /><strong>Not available yet</strong><span>The backend has no storage usage or database connection status endpoint.</span></div></Panel></div>}
    <Modal title="Create user" open={userModal} onClose={() => setUserModal(false)}><form className="camera-form" onSubmit={saveNewUser}><label className="form-label">Username<input className="field-input" minLength="3" maxLength="50" required value={newUser.username} onChange={(event) => setNewUser((current) => ({ ...current, username: event.target.value }))} /></label><label className="form-label">Temporary password<input className="field-input" type="password" minLength="6" autoComplete="new-password" required value={newUser.password} onChange={(event) => setNewUser((current) => ({ ...current, password: event.target.value }))} /></label><label className="form-label">Role<select className="field-input" value={newUser.role} onChange={(event) => setNewUser((current) => ({ ...current, role: event.target.value }))}><option value="admin">Admin</option><option value="reviewer">Reviewer</option><option value="viewer">Viewer</option></select></label>{userError && <ErrorBox error={userError} /> }<div className="modal-actions"><button className="button button-secondary" type="button" onClick={() => setUserModal(false)}>Cancel</button><button className="button button-primary">Create user</button></div></form></Modal>
    <ConfirmDialog open={Boolean(disableTarget)} title="Disable user?" message={`Disable access for ${disableTarget?.username}? They can be enabled again later.`} confirmLabel="Disable user" danger onClose={() => setDisableTarget(null)} onConfirm={() => toggleActive(disableTarget)} />
  </div>
}

