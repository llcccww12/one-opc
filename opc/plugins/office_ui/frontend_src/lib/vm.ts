export interface VmStatus {
  status: 'none' | 'launching' | 'ready' | 'stopped' | 'error'
  cluster_name: string | null
  error_message: string | null
}

async function callVmApi(path: string, method: 'GET' | 'POST', token: string): Promise<VmStatus> {
  try {
    const res = await fetch(path, {
      method,
      headers: { Authorization: `Bearer ${token}` },
    })
    const data = await res.json()
    if (!res.ok || !data.ok) {
      return { status: 'error', cluster_name: null, error_message: data.error ?? '请求失败' }
    }
    return {
      status: data.status,
      cluster_name: data.cluster_name ?? null,
      error_message: data.error_message ?? null,
    }
  } catch {
    return { status: 'error', cluster_name: null, error_message: '网络错误' }
  }
}

export function getVmStatus(token: string): Promise<VmStatus> {
  return callVmApi('/api/vm/status', 'GET', token)
}

export function bindVm(token: string): Promise<VmStatus> {
  return callVmApi('/api/vm/bind', 'POST', token)
}
