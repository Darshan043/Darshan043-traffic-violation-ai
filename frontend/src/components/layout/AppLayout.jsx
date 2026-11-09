import { useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Activity, AlertTriangle, BarChart3, Camera, ChevronLeft, ChevronRight, LayoutDashboard, Menu, Radio, Settings, Shield, X } from 'lucide-react'
import { getMockError, setMockError } from '../../api/index.js'
import { useAuth } from '../../context/AuthContext.jsx'
import { useToast } from '../../context/ToastContext.jsx'
import { useLiveAlerts } from '../../context/LiveAlertsContext.jsx'

const links = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/live', label: 'Live Monitoring', icon: Radio },
  { to: '/violations', label: 'Violations', icon: AlertTriangle },
  { to: '/analytics', label: 'Analytics & Reports', icon: BarChart3 },
  { to: '/cameras', label: 'Camera Management', icon: Camera },
  { to: '/settings', label: 'Settings & Admin', icon: Settings },
]
const titles = Object.fromEntries(links.map(({ to, label }) => [to, label]))

export default function AppLayout() {
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [simulateError, setSimulateError] = useState(getMockError())
  const { user, logout, isMock } = useAuth()
  const toast = useToast()
  const { connected } = useLiveAlerts()
  const navigate = useNavigate()
  const location = useLocation()
  const title = titles[location.pathname] || 'Dashboard'

  const toggleMockError = () => {
    const next = !simulateError
    setMockError(next)
    setSimulateError(next)
    toast(next ? 'Mock API errors are on. Data panels will show their retry state.' : 'Mock API errors are off.', next ? 'info' : 'success')
  }
  const handleLogout = () => { logout(); navigate('/login', { replace: true }) }

  return <div className="app-shell">
    {mobileOpen && <button className="mobile-scrim" type="button" aria-label="Close navigation" onClick={() => setMobileOpen(false)} />}
    <aside className={`sidebar${collapsed ? ' sidebar-collapsed' : ''}${mobileOpen ? ' sidebar-mobile-open' : ''}`}>
      <div className="brand-row"><span className="brand-mark"><Activity size={20} /></span>{!collapsed && <span className="brand-name">Traffic<span>Monitor</span></span>}<button className="icon-button sidebar-toggle" type="button" aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} onClick={() => setCollapsed((value) => !value)}>{collapsed ? <ChevronRight size={17} /> : <ChevronLeft size={17} />}</button><button className="icon-button mobile-close" type="button" aria-label="Close navigation" onClick={() => setMobileOpen(false)}><X size={19} /></button></div>
      <div className="workspace-label">{!collapsed && 'WORKSPACE'}</div>
      <nav className="side-nav" aria-label="Main navigation">{links.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} title={collapsed ? label : undefined} className={({ isActive }) => `nav-link${isActive ? ' nav-link-active' : ''}`} onClick={() => setMobileOpen(false)}><Icon size={19} aria-hidden="true" /><span>{label}</span></NavLink>)}</nav>
      <div className="sidebar-footer"><span className="status-indicator status-green" />{!collapsed && <span>{isMock ? 'Mock environment' : 'API environment'}</span>}</div>
    </aside>
    <main className="main-area">
      <header className="topbar"><button className="icon-button mobile-menu" type="button" aria-label="Open navigation" onClick={() => setMobileOpen(true)}><Menu size={21} /></button><div className="page-heading"><span className="eyebrow">TRAFFIC OPERATIONS</span><h1>{title}</h1></div><div className="topbar-actions">
        <div className="connection-pill"><span className={`status-indicator ${connected ? 'status-green' : 'status-blue'}`} />{connected ? 'Alerts connected' : 'Connecting alerts'}</div>
        {isMock && <button type="button" className={`button button-small ${simulateError ? 'button-error-active' : 'button-quiet'}`} aria-pressed={simulateError} onClick={toggleMockError}>Simulate API error</button>}
        <details className="user-menu"><summary aria-label="User menu"><span className="avatar">{user?.username?.slice(0, 1).toUpperCase() || 'U'}</span><span className="user-menu-label"><strong>{user?.username}</strong><small>{user?.role}</small></span><ChevronRight className="user-chevron" size={15} /></summary><div className="user-menu-popover"><div className="user-menu-role"><Shield size={15} /> Signed in as <strong>{user?.role}</strong></div><button className="button button-secondary" type="button" onClick={handleLogout}>Log out</button></div></details>
      </div></header>
      <div className="content-area"><Outlet /></div>
    </main>
  </div>
}
