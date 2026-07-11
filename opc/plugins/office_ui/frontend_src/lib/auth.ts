const TOKEN_KEY = 'opc_session_token'
const USERNAME_KEY = 'opc_username'

export function getStoredToken(): string | null {
  return window.localStorage.getItem(TOKEN_KEY)
}

export function getStoredUsername(): string | null {
  return window.localStorage.getItem(USERNAME_KEY)
}

export function storeSession(token: string, username: string): void {
  window.localStorage.setItem(TOKEN_KEY, token)
  window.localStorage.setItem(USERNAME_KEY, username)
}

export function clearSession(): void {
  window.localStorage.removeItem(TOKEN_KEY)
  window.localStorage.removeItem(USERNAME_KEY)
}

export function validateCredentials(username: string, inviteCode: string): string | null {
  if (!username.trim()) return '请输入用户名'
  if (!inviteCode.trim()) return '请输入邀请码'
  return null
}

export interface AuthResult {
  ok: boolean
  token?: string
  userId?: string
  error?: string
}

async function postAuth(path: string, username: string, inviteCode: string): Promise<AuthResult> {
  try {
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, invite_code: inviteCode }),
    })
    const data = await res.json()
    if (!res.ok || !data.ok) {
      return { ok: false, error: data.error ?? '请求失败' }
    }
    return { ok: true, token: data.token, userId: data.user_id }
  } catch {
    return { ok: false, error: '网络错误' }
  }
}

export function register(username: string, inviteCode: string): Promise<AuthResult> {
  return postAuth('/api/register', username, inviteCode)
}

export function login(username: string, inviteCode: string): Promise<AuthResult> {
  return postAuth('/api/login', username, inviteCode)
}
