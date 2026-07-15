export interface WorkspaceFileEntry {
  name: string
  is_dir: boolean
  size: number
  mtime: number
}

interface FilesPanelProps {
  currentPath: string
  entries: WorkspaceFileEntry[] | null
  error: string | null
  onNavigate: (path: string) => void
  onRefresh: () => void
  onDelete: (name: string) => void
  downloadUrlFor: (name: string) => string
}

function parentPath(path: string): string {
  const idx = path.lastIndexOf('/')
  return idx === -1 ? '' : path.slice(0, idx)
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let value = bytes / 1024
  let unitIdx = 0
  while (value >= 1024 && unitIdx < units.length - 1) {
    value /= 1024
    unitIdx += 1
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unitIdx]}`
}

export function FilesPanel({ currentPath, entries, error, onNavigate, onRefresh, onDelete, downloadUrlFor }: FilesPanelProps) {
  return (
    <div className="files-panel">
      <div className="files-toolbar">
        <button type="button" className="files-btn" disabled={!currentPath} onClick={() => onNavigate(parentPath(currentPath))}>上一级</button>
        <span className="files-path">{currentPath || '/'}</span>
        <button type="button" className="files-btn" onClick={onRefresh}>刷新</button>
      </div>
      {error && <div className="files-error">{error}</div>}
      <div className="files-card">
        {!entries || entries.length === 0 ? (
          <div className="files-empty">空目录</div>
        ) : (
          <ul className="files-list">
            {entries.map(entry => (
              <li key={entry.name} className="files-row">
                <span className="files-icon">{entry.is_dir ? '📁' : '📄'}</span>
                {entry.is_dir ? (
                  <button
                    type="button"
                    className="files-name files-dir"
                    onClick={() => onNavigate(currentPath ? `${currentPath}/${entry.name}` : entry.name)}
                  >
                    {entry.name}
                  </button>
                ) : (
                  <a className="files-name" href={downloadUrlFor(entry.name)}>{entry.name}</a>
                )}
                {!entry.is_dir && <span className="files-size">{formatSize(entry.size)}</span>}
                <button type="button" className="files-delete" onClick={() => { if (window.confirm(`删除 ${entry.name}？`)) onDelete(entry.name) }}>删除</button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
