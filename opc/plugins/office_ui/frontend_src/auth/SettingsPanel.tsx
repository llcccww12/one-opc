import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'

export interface LlmConfigPayload {
  default_model: string
  api_base: string
  api_key_set: boolean
}

export interface VmCredentialsPayload {
  api_key_set: boolean
  api_base: string
}

interface SettingsPanelProps {
  open: boolean
  onClose: () => void
  llmConfig: LlmConfigPayload | null
  onRequestLlmConfig: () => void
  onSaveLlmConfig: (patch: { default_model?: string; api_base?: string; api_key?: string }) => void
  saveMessage: string
  vmCredentials: VmCredentialsPayload | null
  onRequestVmCredentials: () => void
  onSaveVmCredentials: (patch: { api_key?: string; api_base?: string }) => void
  vmCredentialsSaveMessage: string
}

export function SettingsPanel({
  open,
  onClose,
  llmConfig,
  onRequestLlmConfig,
  onSaveLlmConfig,
  saveMessage,
  vmCredentials,
  onRequestVmCredentials,
  onSaveVmCredentials,
  vmCredentialsSaveMessage,
}: SettingsPanelProps) {
  const [defaultModel, setDefaultModel] = useState('')
  const [apiBase, setApiBase] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [vmApiBase, setVmApiBase] = useState('')
  const [vmApiKey, setVmApiKey] = useState('')

  useEffect(() => {
    if (!open) return
    onRequestLlmConfig()
    onRequestVmCredentials()
  }, [open, onRequestLlmConfig, onRequestVmCredentials])

  useEffect(() => {
    if (!llmConfig) return
    setDefaultModel(llmConfig.default_model)
    setApiBase(llmConfig.api_base)
  }, [llmConfig])

  useEffect(() => {
    if (!vmCredentials) return
    setVmApiBase(vmCredentials.api_base)
  }, [vmCredentials])

  useEffect(() => {
    if (saveMessage === 'Saved') setApiKey('')
  }, [saveMessage])

  useEffect(() => {
    if (vmCredentialsSaveMessage === 'Saved') setVmApiKey('')
  }, [vmCredentialsSaveMessage])

  if (!open) return null

  const handleSave = () => {
    onSaveLlmConfig({
      default_model: defaultModel,
      api_base: apiBase,
      ...(apiKey ? { api_key: apiKey } : {}),
    })
  }

  const handleSaveVmCredentials = () => {
    onSaveVmCredentials({
      api_base: vmApiBase,
      ...(vmApiKey ? { api_key: vmApiKey } : {}),
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
        <div className="org-create-panel">
          <div className="org-create-eyebrow">模型 API Key（用于你的专属云主机）</div>
          <p>
            这个 Key 会被转发给你专属云主机里运行的 Claude Code 使用，不会被其他用户看到或使用。
            可以在 <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noreferrer">Anthropic 官网</a> 申请，
            或使用第三方中转服务提供的 key + Base URL。
          </p>
          <label className="org-create-field">
            <span>API Key {vmCredentials?.api_key_set && !vmApiKey ? '(already set)' : ''}</span>
            <input
              type="password"
              value={vmApiKey}
              onChange={e => setVmApiKey(e.target.value)}
              placeholder={vmCredentials?.api_key_set ? 'Leave blank to keep current key' : ''}
            />
          </label>
          <label className="org-create-field">
            <span>Base URL</span>
            <input value={vmApiBase} onChange={e => setVmApiBase(e.target.value)} placeholder="(default)" />
          </label>
          {vmCredentialsSaveMessage && <div className="org-create-eyebrow">{vmCredentialsSaveMessage}</div>}
          <button type="button" className="settings-save-btn" onClick={handleSaveVmCredentials}>Save</button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
