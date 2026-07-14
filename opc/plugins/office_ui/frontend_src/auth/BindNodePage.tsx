import { useEffect, useRef, useState } from 'react'
import { getStoredToken } from '../lib/auth'
import { bindVm, getVmStatus, type VmStatus } from '../lib/vm'
import './auth.css'

interface BindNodePageProps {
  onReady: () => void
}

const POLL_INTERVAL_MS = 5000

export function BindNodePage({ onReady }: BindNodePageProps) {
  const [vmStatus, setVmStatus] = useState<VmStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const stopPolling = () => {
    if (pollRef.current !== null) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }

  const refresh = async () => {
    const token = getStoredToken()
    if (!token) return
    const result = await getVmStatus(token)
    setVmStatus(result)
    if (result.status === 'ready') {
      stopPolling()
    }
  }

  useEffect(() => {
    refresh()
    return stopPolling
  }, [])

  const startPolling = () => {
    stopPolling()
    pollRef.current = setInterval(refresh, POLL_INTERVAL_MS)
  }

  const handleBind = async () => {
    const token = getStoredToken()
    if (!token) return
    setLoading(true)
    const result = await bindVm(token)
    setLoading(false)
    setVmStatus(result)
    if (result.status === 'launching') {
      startPolling()
    }
  }

  if (vmStatus?.status === 'ready') {
    return (
      <div className="auth-screen">
        <div className="auth-form">
          <h1>云主机已就绪</h1>
          <button type="button" onClick={() => onReady()}>进入工作区</button>
        </div>
      </div>
    )
  }

  return (
    <div className="auth-screen">
      <div className="auth-form">
        <h1>绑定云主机</h1>
        {vmStatus?.status === 'launching' && <div>环境准备中，预计 1~3 分钟...</div>}
        {vmStatus?.status === 'error' && <div className="auth-error">{vmStatus.error_message}</div>}
        {(!vmStatus || vmStatus.status === 'none' || vmStatus.status === 'error') && (
          <button type="button" disabled={loading} onClick={handleBind}>
            {loading ? '处理中...' : '创建云主机'}
          </button>
        )}
        {vmStatus?.status === 'stopped' && (
          <button type="button" disabled={loading} onClick={handleBind}>
            {loading ? '处理中...' : '启动云主机'}
          </button>
        )}
      </div>
    </div>
  )
}
