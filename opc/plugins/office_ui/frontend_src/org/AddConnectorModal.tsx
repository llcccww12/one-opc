import { useEffect, useMemo, useState } from 'react'

export interface AddConnectorPayload {
  name: string
  type: 'local' | 'remote'
  command?: string[]
  url?: string
  headers?: Record<string, string>
  env?: Record<string, string>
  tools_filter?: string[]
}

interface AddConnectorModalProps {
  open: boolean
  onClose: () => void
  onCreate: (payload: AddConnectorPayload) => void
}

function parseKeyValueLines(text: string): Record<string, string> {
  const result: Record<string, string> = {}
  for (const line of text.split('\n')) {
    const separatorIndex = line.indexOf(line.includes('=') ? '=' : ':')
    if (separatorIndex <= 0) continue
    const key = line.slice(0, separatorIndex).trim()
    const value = line.slice(separatorIndex + 1).trim()
    if (key) result[key] = value
  }
  return result
}

export function AddConnectorModal({ open, onClose, onCreate }: AddConnectorModalProps) {
  const [name, setName] = useState('')
  const [type, setType] = useState<'local' | 'remote'>('local')
  const [command, setCommand] = useState('')
  const [url, setUrl] = useState('')
  const [headersText, setHeadersText] = useState('')
  const [envText, setEnvText] = useState('')
  const [toolsFilter, setToolsFilter] = useState('')

  useEffect(() => {
    if (!open) return
    setName('')
    setType('local')
    setCommand('')
    setUrl('')
    setHeadersText('')
    setEnvText('')
    setToolsFilter('')
  }, [open])

  const canCreate = useMemo(() => {
    if (!name.trim()) return false
    return type === 'local' ? command.trim().length > 0 : url.trim().length > 0
  }, [name, type, command, url])

  if (!open) return null

  const submit = () => {
    if (!canCreate) return
    const toolsFilterList = toolsFilter.split(',').map(item => item.trim()).filter(Boolean)
    onCreate({
      name: name.trim(),
      type,
      command: type === 'local' ? command.trim().split(/\s+/) : undefined,
      url: type === 'remote' ? url.trim() : undefined,
      headers: type === 'remote' ? parseKeyValueLines(headersText) : undefined,
      env: type === 'local' ? parseKeyValueLines(envText) : undefined,
      tools_filter: toolsFilterList.length ? toolsFilterList : undefined,
    })
    onClose()
  }

  return (
    <div className="org-create-backdrop" role="presentation" onMouseDown={onClose}>
      <div className="org-create-modal" role="dialog" aria-modal="true" aria-labelledby="add-connector-title" onMouseDown={e => e.stopPropagation()}>
        <div className="org-create-header">
          <div>
            <span className="org-create-eyebrow">New connector</span>
            <h3 id="add-connector-title" className="org-create-title">Add an MCP server</h3>
          </div>
          <button type="button" className="org-create-close" onClick={onClose} aria-label="Close">x</button>
        </div>

        <div className="org-create-panel">
          <label className="org-create-field">
            <span>Name</span>
            <input value={name} onChange={e => setName(e.target.value)} placeholder="github" autoFocus />
          </label>

          <label className="org-create-field">
            <span>Type</span>
            <select value={type} onChange={e => setType(e.target.value as 'local' | 'remote')}>
              <option value="local">Local (stdio command)</option>
              <option value="remote">Remote (URL)</option>
            </select>
          </label>

          {type === 'local' ? (
            <>
              <label className="org-create-field">
                <span>Command</span>
                <input value={command} onChange={e => setCommand(e.target.value)} placeholder="npx -y @modelcontextprotocol/server-github" />
              </label>
              <label className="org-create-field">
                <span>Environment variables (optional, one per line: KEY=value)</span>
                <textarea value={envText} onChange={e => setEnvText(e.target.value)} placeholder="GITHUB_TOKEN=ghp_..." />
              </label>
            </>
          ) : (
            <>
              <label className="org-create-field">
                <span>URL</span>
                <input value={url} onChange={e => setUrl(e.target.value)} placeholder="https://example.com/mcp" />
              </label>
              <label className="org-create-field">
                <span>Headers (optional, one per line: Key: value)</span>
                <textarea value={headersText} onChange={e => setHeadersText(e.target.value)} placeholder="Authorization: Bearer ..." />
              </label>
            </>
          )}

          <label className="org-create-field">
            <span>Tool filter (optional, comma-separated — leave empty to expose every tool)</span>
            <input value={toolsFilter} onChange={e => setToolsFilter(e.target.value)} placeholder="create_issue, list_repos" />
          </label>
        </div>

        <div className="org-create-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" onClick={submit} disabled={!canCreate}>
            Connect
          </button>
        </div>
      </div>
    </div>
  )
}
