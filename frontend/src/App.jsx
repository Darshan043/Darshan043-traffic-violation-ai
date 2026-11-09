import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext.jsx'
import { ToastProvider } from './context/ToastContext.jsx'
import { LiveAlertsProvider } from './context/LiveAlertsContext.jsx'
import AppLayout from './components/layout/AppLayout.jsx'
import ProtectedRoute from './components/common/ProtectedRoute.jsx'
import ErrorBoundary from './components/common/ErrorBoundary.jsx'
import LoginPage from './pages/LoginPage.jsx'
import Loader from './components/common/Loader.jsx'
import './App.css'

const DashboardPage = lazy(() => import('./pages/DashboardPage.jsx'))
const LivePage = lazy(() => import('./pages/LivePage.jsx'))
const ViolationsPage = lazy(() => import('./pages/ViolationsPage.jsx'))
const AnalyticsPage = lazy(() => import('./pages/AnalyticsPage.jsx'))
const CamerasPage = lazy(() => import('./pages/CamerasPage.jsx'))
const SettingsPage = lazy(() => import('./pages/SettingsPage.jsx'))
const pages = [
  { path: 'dashboard', component: DashboardPage },
  { path: 'live', component: LivePage },
  { path: 'violations', component: ViolationsPage },
  { path: 'analytics', component: AnalyticsPage },
  { path: 'cameras', component: CamerasPage },
  { path: 'settings', component: SettingsPage },
]

function AppRoutes() {
  return <Routes>
    <Route path="/login" element={<LoginPage />} />
    <Route element={<ProtectedRoute />}>
      <Route element={<AppLayout />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        {pages.map(({ path, component: Page }) => <Route key={path} path={path} element={<ErrorBoundary><Suspense fallback={<Loader label="Opening page" />}><Page /></Suspense></ErrorBoundary>} />)}
      </Route>
    </Route>
    <Route path="*" element={<Navigate to="/dashboard" replace />} />
  </Routes>
}

export default function App() {
  return <BrowserRouter><AuthProvider><ToastProvider><LiveAlertsProvider><AppRoutes /></LiveAlertsProvider></ToastProvider></AuthProvider></BrowserRouter>
}
