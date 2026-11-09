import { useState } from 'react'
import { Activity, ArrowRight, LockKeyhole } from 'lucide-react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { isMockMode } from '../api/index.js'
import { mockAccounts } from '../mock/data.js'
import { useAuth } from '../context/AuthContext.jsx'

export default function LoginPage() {
  const { login, user } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  if (user) return <Navigate to="/dashboard" replace />

  const submit = async (event) => {
    event.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login({ username, password })
      setPassword('')
      navigate(location.state?.from?.pathname || '/dashboard', { replace: true })
    } catch (loginError) {
      setError(loginError.message || 'Sign-in failed. Try again.')
      setPassword('')
    } finally { setLoading(false) }
  }

  return <main className="login-page"><section className="login-card"><div className="login-brand"><span className="brand-mark"><Activity size={22} /></span><div><strong>Traffic Violation Monitor</strong><span>Road safety operations</span></div></div><div className="login-title"><div className="login-icon"><LockKeyhole size={20} /></div><h1>Welcome back</h1><p>Sign in to view your traffic operations.</p></div>
    <form onSubmit={submit} className="login-form"><label htmlFor="username">Username</label><input id="username" name="username" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required /><label htmlFor="password">Password</label><input id="password" name="password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required />{error && <div className="login-error" role="alert">{error}</div>}<button className="button button-primary login-submit" type="submit" disabled={loading}>{loading ? 'Signing in…' : 'Sign in'}<ArrowRight size={17} /></button></form>
    {isMockMode() && <section className="mock-credentials" aria-label="Mock account credentials"><strong>Mock only · demo accounts</strong><span>These fake credentials are only accepted in mock mode.</span><div className="demo-account-list">{mockAccounts.map((account) => <button type="button" key={account.username} onClick={() => { setUsername(account.username); setPassword(account.password) }}><span><b>{account.username}</b><small>{account.role}</small></span><code>{account.password}</code></button>)}</div></section>}
    <p className="login-footnote">Your password is used for sign-in only and is never saved.</p>
  </section></main>
}
