import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { clearSession, getStoredUsername } from '../lib/auth'
import { SettingsPanel, type LlmConfigPayload, type VmCredentialsPayload } from './SettingsPanel'
import './identityMenu.css'

interface IdentityMenuProps {
  llmConfig: LlmConfigPayload | null
  onRequestLlmConfig: () => void
  onSaveLlmConfig: (patch: { default_model?: string; api_base?: string; api_key?: string }) => void
  saveMessage: string
  vmCredentials: VmCredentialsPayload | null
  onRequestVmCredentials: () => void
  onSaveVmCredentials: (patch: { api_key?: string; api_base?: string }) => void
  vmCredentialsSaveMessage: string
}

export function IdentityMenu({
  llmConfig,
  onRequestLlmConfig,
  onSaveLlmConfig,
  saveMessage,
  vmCredentials,
  onRequestVmCredentials,
  onSaveVmCredentials,
  vmCredentialsSaveMessage,
}: IdentityMenuProps) {
  const [open, setOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [popoverStyle, setPopoverStyle] = useState<CSSProperties>({})
  const wrapperRef = useRef<HTMLDivElement>(null)
  const avatarRef = useRef<HTMLButtonElement>(null)
  const popoverRef = useRef<HTMLDivElement>(null)
  const username = getStoredUsername()

  useEffect(() => {
    const onOutsideClick = (e: MouseEvent) => {
      if (
        wrapperRef.current && !wrapperRef.current.contains(e.target as Node) &&
        popoverRef.current && !popoverRef.current.contains(e.target as Node)
      ) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onOutsideClick)
    return () => document.removeEventListener('mousedown', onOutsideClick)
  }, [])

  useEffect(() => {
    if (!open || !avatarRef.current) return
    // .rail clips overflowing descendants (needed for its width-collapse transition),
    // which also clips absolutely-positioned popovers from hit-testing. Escape it by
    // positioning the popover with `fixed` at the avatar's on-screen coordinates.
    const rect = avatarRef.current.getBoundingClientRect()
    setPopoverStyle({
      position: 'fixed',
      left: rect.left,
      bottom: window.innerHeight - rect.top + 6,
    })
  }, [open])

  if (!username) return null

  const handleLogout = () => {
    clearSession()
    window.location.reload()
  }

  return (
    <div className="identity-wrap" ref={wrapperRef}>
      <button type="button" className="identity-avatar" ref={avatarRef} onClick={() => setOpen(o => !o)} title={username}>
        {username.charAt(0).toUpperCase()}
      </button>
      {open && createPortal(
        <div className="identity-popover" role="menu" style={popoverStyle} ref={popoverRef}>
          <div className="identity-popover-username">{username}</div>
          <button type="button" className="identity-popover-item" role="menuitem" onClick={() => { setSettingsOpen(true); setOpen(false) }}>
            模型 / API Key 设置
          </button>
          <button type="button" className="identity-popover-item" role="menuitem" onClick={handleLogout}>
            退出登录
          </button>
        </div>,
        document.body,
      )}
      <SettingsPanel
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        llmConfig={llmConfig}
        onRequestLlmConfig={onRequestLlmConfig}
        onSaveLlmConfig={onSaveLlmConfig}
        saveMessage={saveMessage}
        vmCredentials={vmCredentials}
        onRequestVmCredentials={onRequestVmCredentials}
        onSaveVmCredentials={onSaveVmCredentials}
        vmCredentialsSaveMessage={vmCredentialsSaveMessage}
      />
    </div>
  )
}
