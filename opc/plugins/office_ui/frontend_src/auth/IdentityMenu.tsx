import { useEffect, useRef, useState } from 'react'
import { clearSession, getStoredUsername } from '../lib/auth'
import { SettingsPanel, type LlmConfigPayload } from './SettingsPanel'
import './identityMenu.css'

interface IdentityMenuProps {
  llmConfig: LlmConfigPayload | null
  onRequestLlmConfig: () => void
  onSaveLlmConfig: (patch: { default_model?: string; api_base?: string; api_key?: string }) => void
  saveMessage: string
}

export function IdentityMenu({ llmConfig, onRequestLlmConfig, onSaveLlmConfig, saveMessage }: IdentityMenuProps) {
  const [open, setOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const wrapperRef = useRef<HTMLDivElement>(null)
  const username = getStoredUsername()

  useEffect(() => {
    const onOutsideClick = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onOutsideClick)
    return () => document.removeEventListener('mousedown', onOutsideClick)
  }, [])

  if (!username) return null

  const handleLogout = () => {
    clearSession()
    window.location.reload()
  }

  return (
    <div className="identity-wrap" ref={wrapperRef}>
      <button type="button" className="identity-avatar" onClick={() => setOpen(o => !o)} title={username}>
        {username.charAt(0).toUpperCase()}
      </button>
      {open && (
        <div className="identity-popover" role="menu">
          <div className="identity-popover-username">{username}</div>
          <button type="button" className="identity-popover-item" role="menuitem" onClick={() => { setSettingsOpen(true); setOpen(false) }}>
            模型 / API Key 设置
          </button>
          <button type="button" className="identity-popover-item" role="menuitem" onClick={handleLogout}>
            退出登录
          </button>
        </div>
      )}
      <SettingsPanel
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        llmConfig={llmConfig}
        onRequestLlmConfig={onRequestLlmConfig}
        onSaveLlmConfig={onSaveLlmConfig}
        saveMessage={saveMessage}
      />
    </div>
  )
}
