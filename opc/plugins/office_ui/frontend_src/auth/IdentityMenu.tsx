import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { SettingsPanel, type LlmConfigPayload } from './SettingsPanel'
import './identityMenu.css'

interface IdentityMenuProps {
  llmConfig: LlmConfigPayload | null
  onRequestLlmConfig: () => void
  onSaveLlmConfig: (patch: { default_model?: string; api_base?: string; api_key?: string }) => void
  saveMessage: string
}

export function IdentityMenu({
  llmConfig,
  onRequestLlmConfig,
  onSaveLlmConfig,
  saveMessage,
}: IdentityMenuProps) {
  const [open, setOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [popoverStyle, setPopoverStyle] = useState<CSSProperties>({})
  const wrapperRef = useRef<HTMLDivElement>(null)
  const avatarRef = useRef<HTMLButtonElement>(null)
  const popoverRef = useRef<HTMLDivElement>(null)

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
    const rect = avatarRef.current.getBoundingClientRect()
    setPopoverStyle({
      position: 'fixed',
      left: rect.left,
      bottom: window.innerHeight - rect.top + 6,
    })
  }, [open])

  return (
    <div className="identity-wrap" ref={wrapperRef}>
      <button type="button" className="identity-avatar" ref={avatarRef} onClick={() => setOpen(o => !o)} title="Settings">
        S
      </button>
      {open && createPortal(
        <div className="identity-popover" role="menu" style={popoverStyle} ref={popoverRef}>
          <button type="button" className="identity-popover-item" role="menuitem" onClick={() => { setSettingsOpen(true); setOpen(false) }}>
            模型 / API Key 设置
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
      />
    </div>
  )
}
