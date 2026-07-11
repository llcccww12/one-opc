import { useState } from 'react'
import App from '../App'
import { LoginScreen } from './LoginScreen'
import { getStoredToken } from '../lib/auth'

export default function Root() {
  const [authenticated, setAuthenticated] = useState<boolean>(getStoredToken() !== null)
  if (!authenticated) {
    return <LoginScreen onAuthenticated={() => setAuthenticated(true)} />
  }
  return <App />
}
