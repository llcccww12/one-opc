import { useState, type FormEvent } from 'react'
import { login, register, storeSession, validateCredentials } from '../lib/auth'
import './auth.css'

interface LoginScreenProps {
  onAuthenticated: () => void
}

export function LoginScreen({ onAuthenticated }: LoginScreenProps) {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [username, setUsername] = useState('')
  const [inviteCode, setInviteCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    const validationError = validateCredentials(username, inviteCode)
    if (validationError) {
      setError(validationError)
      return
    }
    setSubmitting(true)
    setError(null)
    const result = mode === 'login' ? await login(username, inviteCode) : await register(username, inviteCode)
    setSubmitting(false)
    if (!result.ok || !result.token) {
      setError(result.error ?? (mode === 'login' ? '登录失败' : '注册失败'))
      return
    }
    storeSession(result.token, username)
    onAuthenticated()
  }

  return (
    <div className="app-shell auth-screen">
      <form className="auth-form" onSubmit={handleSubmit}>
        <h1>{mode === 'login' ? '登录' : '注册'}</h1>
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="用户名"
          autoComplete="username"
        />
        <input
          value={inviteCode}
          onChange={(e) => setInviteCode(e.target.value)}
          placeholder="邀请码"
          type="password"
          autoComplete="off"
        />
        {error && <div className="auth-error">{error}</div>}
        <button type="submit" disabled={submitting}>
          {submitting ? '处理中...' : mode === 'login' ? '登录' : '注册'}
        </button>
        <button
          type="button"
          className="auth-switch"
          onClick={() => {
            setMode(mode === 'login' ? 'register' : 'login')
            setError(null)
          }}
        >
          {mode === 'login' ? '没有账号？注册' : '已有账号？登录'}
        </button>
      </form>
    </div>
  )
}
