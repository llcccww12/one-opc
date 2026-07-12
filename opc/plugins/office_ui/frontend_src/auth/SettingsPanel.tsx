import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'

export interface LlmConfigPayload {
  default_model: string
  api_base: string
  api_key_set: boolean
}

interface SettingsPanelProps {
  open: boolean
  onClose: () => void
  llmConfig: LlmConfigPayload | null
  onRequestLlmConfig: () => void
  onSaveLlmConfig: (patch: { default_model?: string; api_base?: string; api_key?: string }) => void
  saveMessage: string
}

export function SettingsPanel({ open, onClose, llmConfig, onRequestLlmConfig, onSaveLlmConfig, saveMessage }: SettingsPanelProps) {
  const [defaultModel, setDefaultModel] = useState('')
  const [apiBase, setApiBase] = useState('')
  const [apiKey, setApiKey] = useState('')

  useEffect(() => {
    if (!open) return
    onRequestLlmConfig()
  }, [open, onRequestLlmConfig])

  useEffect(() => {
    if (!llmConfig) return
    setDefaultModel(llmConfig.default_model)
    setApiBase(llmConfig.api_base)
  }, [llmConfig])

  useEffect(() => {
    if (saveMessage === 'Saved') setApiKey('')
  }, [saveMessage])

  if (!open) return null

  const handleSave = () => {
    onSaveLlmConfig({
      default_model: defaultModel,
      api_base: apiBase,
      ...(apiKey ? { api_key: apiKey } : {}),
    })
  }

  return createPortal(
    <div className="settings-backdrop" role="presentation" onMouseDown={onClose}>
      <div className="settings-modal" role="dialog" aria-modal="true" aria-labelledby="settings-panel-title" onMouseDown={e => e.stopPropagation()}>
        <div className="org-create-header">
          <div>
            <span className="org-create-eyebrow">Settings</span>
            <h3 id="settings-panel-title" className="org-create-title">Model / API Key</h3>
          </div>
          <button type="button" className="org-create-close" onClick={onClose} aria-label="Close">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
        <div className="org-create-panel">
          <label className="org-create-field">
            <span>Model</span>
            <input value={defaultModel} onChange={e => setDefaultModel(e.target.value)} placeholder="anthropic/claude-sonnet-4-20250514" />
          </label>
          <label className="org-create-field">
            <span>API Key {llmConfig?.api_key_set && !apiKey ? '(already set)' : ''}</span>
            <input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder={llmConfig?.api_key_set ? 'Leave blank to keep current key' : ''} />
          </label>
          <label className="org-create-field">
            <span>Base URL</span>
            <input value={apiBase} onChange={e => setApiBase(e.target.value)} placeholder="(default)" />
          </label>
          {saveMessage && <div className="org-create-eyebrow">{saveMessage}</div>}
          <button type="button" className="settings-save-btn" onClick={handleSave}>Save</button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
