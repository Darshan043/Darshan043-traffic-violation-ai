import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext.jsx'
import { can } from '../../context/permissions.js'
import Loader from './Loader.jsx'

export default function ProtectedRoute({ action = 'view' }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <Loader label="Checking your session" />
  if (!user) return <Navigate to="/login" replace state={{ from: location }} />
  if (!can(user.role, action)) return <Navigate to="/dashboard" replace />
  return <Outlet />
}
