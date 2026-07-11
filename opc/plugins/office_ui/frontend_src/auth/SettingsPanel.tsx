import { useEffect, useState } from 'react'

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

  return (
    <div className="org-create-backdrop" role="presentation" onMouseDown={onClose}>
      <div className="org-create-modal" role="dialog" aria-modal="true" aria-labelledby="settings-panel-title" onMouseDown={e => e.stopPropagation()}>
        <div className="org-create-header">
          <div>
            <span className="org-create-eyebrow">Settings</span>
            <h3 id="settings-panel-title" className="org-create-title">Model / API Key</h3>
          </div>
          <button type="button" className="org-create-close" onClick={onClose} aria-label="Close">x</button>
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
          <button type="button" className="org-create-close" onClick={handleSave}>Save</button>
        </div>
      </div>
    </div>
  )
}
