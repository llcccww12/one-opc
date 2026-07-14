import { useEffect, useState } from 'react'
import App from '../App'
import { LoginScreen } from './LoginScreen'
import { BindNodePage } from './BindNodePage'
import { getStoredToken } from '../lib/auth'
import { getVmStatus } from '../lib/vm'

export default function Root() {
  const [authenticated, setAuthenticated] = useState<boolean>(getStoredToken() !== null)
  const [vmReady, setVmReady] = useState<boolean>(false)

  useEffect(() => {
    if (!authenticated) return
    const token = getStoredToken()
    if (!token) return
    getVmStatus(token).then((result) => {
      if (result.status === 'ready') setVmReady(true)
    })
  }, [authenticated])

  if (!authenticated) {
    return <LoginScreen onAuthenticated={() => setAuthenticated(true)} />
  }
  if (!vmReady) {
    return <BindNodePage onReady={() => setVmReady(true)} />
  }
  return <App />
}
