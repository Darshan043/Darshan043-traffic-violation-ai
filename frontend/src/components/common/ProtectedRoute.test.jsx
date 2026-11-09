import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

const { authState } = vi.hoisted(() => ({ authState: { user: null, loading: false } }))
vi.mock('../../context/AuthContext.jsx', () => ({ useAuth: () => authState }))

import ProtectedRoute from './ProtectedRoute.jsx'

function LoginDestination() {
  const location = useLocation()
  return <div>Login redirect from {location.state?.from?.pathname}</div>
}

describe('ProtectedRoute', () => {
  it('redirects logged-out users to login and preserves their requested path', () => {
    authState.user = null
    authState.loading = false
    render(<MemoryRouter initialEntries={['/private']}><Routes><Route element={<ProtectedRoute />}><Route path="/private" element={<div>Private data</div>} /></Route><Route path="/login" element={<LoginDestination />} /></Routes></MemoryRouter>)
    expect(screen.getByText('Login redirect from /private')).toBeInTheDocument()
    expect(screen.queryByText('Private data')).not.toBeInTheDocument()
  })

  it('shows a loading state while authentication is being checked', () => {
    authState.user = null
    authState.loading = true
    render(<MemoryRouter initialEntries={['/private']}><Routes><Route element={<ProtectedRoute />}><Route path="/private" element={<div>Private data</div>} /></Route><Route path="/login" element={<div>Login page</div>} /></Routes></MemoryRouter>)
    expect(screen.getByRole('status')).toHaveTextContent('Checking your session')
  })
})
